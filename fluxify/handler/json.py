from fluxify.handler.conditions import handle_conditions
from fluxify.helper.yamlparser import apply_value
from fluxify.transformers.transformer import handle_transformations
from fluxify.utils import Utils
import parser
import gc


class JSONHandler:

    def __init__(self, filepath, mapping, root_node=None, error_tolerance=False, bulksize=100, save_unmatched=True, unmatched_key='unmatched'):
        self.__filepath = filepath
        self.__mapping = mapping
        self.__root_node = root_node
        self.__error_tolerance = error_tolerance
        self.__bulksize = bulksize
        self.__save_unmatched = save_unmatched
        self.__unmatched_key = unmatched_key

        self.__content = None

        self.__stats = {
            'total_count': 0
        }

    def process(self):
        import json

        with open(self.__filepath, 'r') as fh:
            jsoncontent = fh.read()
            self.json = json.loads(jsoncontent)

        result = []
        content = self.json

        if type(self.__root_node) is not str:
            iterator = iter(content)
        else:
            iterator = iter(content[self.__root_node])

        for jsonitem in iterator:
            # Updating stats
            self.__stats['total_count'] += 1

            item = {}
            for yaml_key, yaml_value in self.__mapping.items():
                if 'col' in yaml_value:
                    col = yaml_value['col']

                    multiple = None
                    value_index = None
                    default = None

                    if 'multiple' in yaml_value:
                        multiple = yaml_value['multiple']

                    if 'index' in yaml_value:
                        val_index = yaml_value['index']
                        if type(val_index) is int:
                            value_index = val_index

                    if 'default' in yaml_value:
                        default = yaml_value['default']

                    if col == '_all_':
                        finalvalue = jsonitem
                    else:
                        finalvalue = self.get(col, jsonitem, multiple, value_index, default)

                    if 'transformations' in yaml_value:
                        finalvalue = handle_transformations(yaml_value['transformations'], finalvalue, error_tolerance=self.__error_tolerance)

                    item = apply_value(item, yaml_key, finalvalue)

                    if 'conditions' in yaml_value:
                        finalvalue = handle_conditions(yaml_value['conditions'], item, jsonitem)
                        item = apply_value(item, yaml_key, finalvalue)

                    # Deleting the value from original input object
                    if self.__save_unmatched:
                        self.__delete(col, jsonitem)
                elif 'value' in yaml_value:
                    finalvalue = yaml_value['value']
                    if type(finalvalue) == str:
                        finalvalue = finalvalue.replace('$subject', 'item')
                        expr = parser.expr(finalvalue)
                        finalvalue = eval(expr.compile(''))

                    # Clean if NaN
                    finalvalue = Utils.clean_if_nan(finalvalue)

                    item = apply_value(item, yaml_key, finalvalue)

                    if 'conditions' in yaml_value:
                        finalvalue = handle_conditions(yaml_value['conditions'], item)
                        item = apply_value(item, yaml_key, finalvalue)
                elif 'conditions' in yaml_value:
                    finalvalue = handle_conditions(yaml_value['conditions'], item)

                    # Set to None if value is NaN
                    Utils.clean_if_nan(finalvalue)

                    item = apply_value(item, yaml_key, finalvalue)

            # Unmatched
            if self.__save_unmatched:
                item[self.__unmatched_key] = self.__get_unmatched(jsonitem)

            result.append(item)

        return result

    def lazy_process(self):
        import ijson

        root_node = 'item'
        if self.__root_node is not None and type(self.__root_node) is str:
            root_node = '{}.item'.format(self.__root_node)

        with open(self.__filepath, 'rb') as fh:
            self.__content = ijson.items(fh, root_node)
            results = []
            it = 0

            # Iterating over JSON generator
            for jsonobject in self.__content:
                # Updating stats
                self.__stats['total_count'] += 1

                item = {}

                # For each JSON Object, iterating over the YAML mapping and retrieving data
                for yaml_key, yaml_value in self.__mapping.items():

                    if 'col' in yaml_value:
                        col = yaml_value['col']

                        multiple = None
                        value_index = None
                        default = None

                        if 'multiple' in yaml_value:
                            multiple = yaml_value['multiple']

                        if 'index' in yaml_value:
                            val_index = yaml_value['index']
                            if type(val_index) is int:
                                value_index = val_index

                        if 'default' in yaml_value:
                            default = yaml_value['default']

                        if col == '_all_':
                            finalvalue = jsonobject
                        else:
                            finalvalue = self.get(col, jsonobject, multiple, value_index, default)

                        # If transformations are defined in the mapping, applying them
                        if 'transformations' in yaml_value:
                            finalvalue = handle_transformations(yaml_value['transformations'], finalvalue, error_tolerance=self.__error_tolerance)

                        item = apply_value(item, yaml_key, finalvalue)

                        # Handling conditions
                        if 'conditions' in yaml_value:
                            finalvalue = handle_conditions(yaml_value['conditions'], item, jsonobject)
                            item = apply_value(item, yaml_key, finalvalue)

                        # Deleting the value from original input object
                        if self.__save_unmatched:
                            self.__delete(col, jsonobject)

                    elif 'value' in yaml_value:
                        finalvalue = yaml_value['value']
                        if type(finalvalue) == str:
                            finalvalue = finalvalue.replace('$subject', 'item')
                            expr = parser.expr(finalvalue)
                            finalvalue = eval(expr.compile(''))

                        # Set to None if value is NaN
                        finalvalue = Utils.clean_if_nan(finalvalue)

                        item = apply_value(item, yaml_key, finalvalue)

                        if 'conditions' in yaml_value:
                            finalvalue = handle_conditions(yaml_value['conditions'], item)
                            item = apply_value(item, yaml_key, finalvalue)
                    elif 'conditions' in yaml_value:
                        finalvalue = handle_conditions(yaml_value['conditions'], item)
                        item = apply_value(item, yaml_key, finalvalue)
                    else:
                        text = '{} : No supported options found in mapping. Supported: [col, value, conditions]'.format(yaml_key)
                        if self.__error_tolerance:
                            Utils.log('error', text)
                            continue
                        else:
                            raise Exception(text)

                # Unmatched
                if self.__save_unmatched:
                    item[self.__unmatched_key] = self.__get_unmatched(jsonobject)

                results.append(item)

                if len(results) % self.__bulksize == 0:
                    self.__callback(results)
                    results = []
                    gc.collect()

            if len(results) > 0:
                self.__callback(results)
                results = []
                gc.collect()

    def get(self, key, subject, multiple=None, value_index=None, default=None):
        split = key.split('.')
        split_count = len(split)
        for index, val in enumerate(split):
            if val not in subject:
                if default is None:
                    return False
                else:
                    return default

            it = index + 1

            if it == split_count:
                subject = subject[val]
                if type(subject) is list and len(subject) > 0:
                    if type(value_index) is int:
                        try:
                            subject = subject[value_index]
                        except:
                            if default is None:
                                return False
                            else:
                                return default
                    elif type(value_index) is str:
                        if value_index == 'first':
                            subject = subject[0]
                        elif value_index == 'last':
                            subject = subject[-1]
            else:
                subject = subject[val]

        # Set to None if value is NaN
        subject = Utils.clean_if_nan(subject)

        return subject

    def __delete(self, key: str, subject):
        split = key.split('.')
        for ix, val in enumerate(split):
            if val not in subject:
                return False

            if ix != len(split) - 1:
                subject = subject[val]
            else:
                del subject[val]

        return True

    def __get_unmatched(self, item: dict):
        unmatched = {}
        for (key, value) in item.items():
            if not Utils.empty(value):
                value = Utils.clean_if_nan(value)
                if value is not None:
                    unmatched[key] = value

        return unmatched

    def set_bulksize(self, size):
        self.__bulksize = size

    def set_callback(self, callback):
        self.__callback = callback

    def get_stats(self):
        return self.__stats
