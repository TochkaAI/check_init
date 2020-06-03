import json
from multiprocessing import Process, Manager
import os
import re
import subprocess
import sys
import yaml

import clang.cindex
import datetime

from multiprocessing.managers import SyncManager, MakeProxyType

BaseSetProxy = MakeProxyType('BaseSetProxy', ([
    '__and__', '__contains__', '__iand__', '__ior__',
    '__isub__', '__ixor__', '__len__', '__or__', '__rand__', '__ror__', '__rsub__',
    '__rxor__', '__sub__', '__xor__', 'add', 'clear', 'copy', 'difference',
    'difference_update', 'discard', 'intersection', 'intersection_update', 'isdisjoint',
    'issubset', 'issuperset', 'pop', 'remove', 'symmetric_difference',
    'symmetric_difference_update', 'union', 'update']
    ))
# class SetProxy(BaseSetProxy):
    # def __iand__(self, value):
    #     self._callmethod('__iand__', (value,))
    #     return self
    # def __ior__(self, value):
    #     self._callmethod('__ior__', (value,))
    #     return self
    # def __isub__(self, value):
    #     self._callmethod('__isub__', (value,))
    #     return self
    # def __ixor__(self, value):
    #     self._callmethod('__ixor__', (value,))
    #     return self

SyncManager.register('set', set, BaseSetProxy)

manager = Manager()
manager.register('set', set)
# Список enum, объявленных в заголовочных файлах
enums = manager.set()
# enums = []
# Список struct, объявленных в заголовочных файлах
structs = manager.set()
# structs = []
# Список struct из входного файла, которые есть в списке structs
used_structs = []

# Список базовых типов
base_types = ['bool', 'char', 'signed char', 'unsigned char',
              'short', 'unsigned short', 'ushort',
              'int', 'unsigned int', 'uint',
              'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t',
              'qint8', 'qint16', 'qint32', 'qint64',
              'quint8', 'quint16', 'quint32', 'quint64',
              'long', 'unsigned long', 'ulong', 'long long',
              'unsigned long long', 'qlonglong',
              'float', 'double', 'long double']

base_literals = [clang.cindex.CursorKind.INTEGER_LITERAL, clang.cindex.CursorKind.FLOATING_LITERAL,
                 clang.cindex.CursorKind.CXX_BOOL_LITERAL_EXPR, clang.cindex.CursorKind.STRING_LITERAL,
                 clang.cindex.CursorKind.CHARACTER_LITERAL, clang.cindex.CursorKind.UNEXPOSED_EXPR]

base_kinds = [
    clang.cindex.TypeKind.BOOL,
    clang.cindex.TypeKind.CHAR_U,
    clang.cindex.TypeKind.UCHAR,
    clang.cindex.TypeKind.CHAR16,
    clang.cindex.TypeKind.CHAR32,
    clang.cindex.TypeKind.USHORT,
    clang.cindex.TypeKind.UINT,
    clang.cindex.TypeKind.ULONG,
    clang.cindex.TypeKind.ULONGLONG,
    clang.cindex.TypeKind.CHAR_S,
    clang.cindex.TypeKind.SHORT,
    clang.cindex.TypeKind.INT,
    clang.cindex.TypeKind.LONG,
    clang.cindex.TypeKind.LONGLONG,
    clang.cindex.TypeKind.FLOAT,
    clang.cindex.TypeKind.DOUBLE,
    clang.cindex.TypeKind.LONGDOUBLE
]

cur_struct = None
uninitialized = manager.dict()
# uninitialized = {}

parsing_files = []


def find_header_enums_and_structs(cursor, file):
    # print(file)
    # print(cursor.spelling)
    if cursor.location.file is not None and cursor.location.file.name == file and cursor.spelling is not '':
        if cursor.kind == clang.cindex.CursorKind.STRUCT_DECL:
            structs.add(cursor.spelling)
            # structs.append(cursor.spelling)
        elif cursor.kind == clang.cindex.CursorKind.ENUM_DECL:
            enums.add(cursor.spelling)
            # enums.append(cursor.spelling)

    children = cursor.get_children()
    for c in children:
        find_header_enums_and_structs(c, file)


def parse_header_file(file):
    index = clang.cindex.Index.create()
    tu = index.parse(file, args=['-x', 'c++'])
    find_header_enums_and_structs(tu.cursor, file)


def find_input_structs(cursor):
    if cursor.kind == clang.cindex.CursorKind.STRUCT_DECL:
        # for struct in structs:
            if structs.__contains__(cursor.spelling):
            # if struct == cursor.spelling:
                used_structs.append(cursor.spelling)
                # print('struct ' + struct)
                find_unused_vars(cursor)
                # print('\n')
                # break

    for c in cursor.get_children():
        find_input_structs(c)


def parse_input_file(cmd, num):
    include = False
    for project in include_projects:
        if re.match(r'^.*\/' + project + r'\/', cmd['file']) is not None:
            include = True
            break
    if not include:
        return
    # print(cmd['file'])
    arguments = cmd['arguments']
    args = [arguments[0]]
    for j in range(1, len(arguments)):
        arg = arguments[j]
        if arg.startswith('-fPIC'):
            args.append(arg)
        elif arg.startswith('-D') or arg.startswith('-I'):
            args.append(arg)
        elif arg.startswith('-isystem'):  # Добавляем элемент -isystem и следующий за ним
            args.append(arg)
            args.append(arguments[j + 1])
            j = j + 1
        elif arg.startswith('-std='):
            args.append(arg)
        j = j + 1
    # args.append('-std=c++14')
    args.append('-E')
    args.append(cmd['file'])
    args.append('>')
    args.append('temp' + str(num) + '.txt')
    str_args = ' '
    str_args = str_args.join(args)
    compile = subprocess.call(str_args, shell=True)
    if compile != 0:
        print('Compile file: ' + cmd['file'] + ' exited with code ' + compile)
        exit(1)
    file_name = 'temp' + str(num) + '.h'
    reformat_file = subprocess.call('sed \'/#/d\' temp' + str(num) + '.txt > ' + file_name, shell=True)

    index = clang.cindex.Index.create()
    tu = index.parse(file_name, args=['-x', 'c++'])
    find_input_structs(tu.cursor)


def find_unused_vars(cursor):
    # print('\t' + str(cursor.spelling) + '<' + str(cursor.kind) + '>')
    # if cursor.spelling == 'CommandNameLog':
    #     print('')

    # Если тип - объявление структуры, то начинаем рекурсивный обход по дереву потомков этой структуры
    if cursor.kind == clang.cindex.CursorKind.STRUCT_DECL:
        global cur_struct
        if cur_struct != cursor.spelling:
            cur_struct = cursor.spelling
            parent = cursor.lexical_parent
            if parent is not None and parent.lexical_parent is not None:
                if parent.lexical_parent is not None:
                    cur_struct = parent.spelling + ':' + cur_struct
                    parent = parent.lexical_parent
                    while parent.lexical_parent is not None:
                        cur_struct = parent.spelling + ':' + cur_struct
                        parent = parent.lexical_parent
        for c in cursor.get_children():
            find_unused_vars(c)

    # Если тип - объявление переменной, то начинаем рекурсивный обход по дереву потомков этой переменной
    if cursor.kind == clang.cindex.CursorKind.FIELD_DECL:
        is_init = False
        # Если тип переменной - один из базовых
        if cursor.type.kind in base_kinds:
            # Получаем список потомков
            # Если в списке есть потомок с фигурными скобками '{' или одним из литералов - переменная инициализирована
            var_children = cursor.get_children()
            for var_ch in var_children:
                if var_ch.kind == clang.cindex.CursorKind.INIT_LIST_EXPR:
                    init_children = var_ch.get_children()
                    for init_ch in init_children:
                        if init_ch.type.kind in base_kinds:
                            is_init = True
                            break
                elif var_ch.kind in base_literals:
                    is_init = True
                    break
            # Если тип переменной интерпретирован как INT и она не была инициализирована - возможно ее тип enum,
            # который не был подключен с заголовочным файлом. В таком случае открываем файл, находим это строку
            # и проверям реальный тип переменной (int или enum)
            if cursor.type.kind == clang.cindex.TypeKind.INT and not is_init:
                lines = open(str(cursor.location.file), 'r').readlines()
                i = 0
                for line in lines:
                    i = i + 1
                    if i == cursor.location.line:
                        line = line.strip().replace(';', '')
                        res = re.match(r'^int\s', line)
                        if res is None:
                            match = re.match(r'^([a-zA-Z].*)\s([a-zA-Z].*)', line)
                            type = ''
                            if match is not None:
                                type = match.group(1)
                            print('struct ' + cur_struct + ':')
                            print('\tvariable ' + line + ' is interpreted as INT. Check include header with "' +
                                  type + '" essence')
        # Если тип переменной - enum
        elif cursor.type.kind == clang.cindex.TypeKind.ENUM:
            # Получаем список потомков
            # Если в списке есть потомок с фигурными скобками '{', получаем список его потомков - если в нем есть
            # потомок с выражением, которое относится к некоторому объявлению значения - переменная инициализирована
            var_children = cursor.get_children()
            for var_ch in var_children:
                if var_ch.kind == clang.cindex.CursorKind.INIT_LIST_EXPR:
                    init_children = var_ch.get_children()
                    for init_ch in init_children:
                        if init_ch.kind == clang.cindex.CursorKind.DECL_REF_EXPR:
                            is_init = True
                else:
                    init_children = var_ch.get_children()
                    for init_ch in init_children:
                        is_init = True
                        break
        # Если тип переменной - typedef
        # Часть типов попадает в базовые типы
        elif cursor.type.kind == clang.cindex.TypeKind.TYPEDEF:
            if cursor.type.spelling not in base_types:
                is_init = True
            else:
                # Получаем список потомков
                # Если в списке есть потомок с фигурными скобками '{' или
                # одним из литералов - переменная инициализирована
                var_children = cursor.get_children()
                for var_ch in var_children:
                    if var_ch.kind == clang.cindex.CursorKind.INIT_LIST_EXPR:
                        init_children = var_ch.get_children()
                        for init_ch in init_children:
                            is_init = True
                            break
                    elif var_ch.kind in base_literals:
                        is_init = True
                        break
        # Если тип переменной - классы qt, структуры и др.
        elif cursor.type.kind == clang.cindex.TypeKind.RECORD or cursor.type.kind == clang.cindex.TypeKind.UNEXPOSED:
            is_init = True
        else:
            is_init = True

        variable = cursor.type.spelling + ' ' + cursor.spelling
        if not is_init and cur_struct not in uninitialized:
            uninitialized[cur_struct] = []
        if not is_init and variable not in uninitialized[cur_struct]:
            vars = uninitialized[cur_struct]
            vars.append(variable)
            uninitialized[cur_struct] = vars
        # if not is_init and variable not in uninitialized[cur_struct]:
        #     uninitialized[cur_struct].append(variable)


if __name__ == '__main__':
    try:
        start = datetime.datetime.now()
        # print(start)
        if len(sys.argv) != 4:
            print('Bad arguments length')
            exit(1)
        conf_file = sys.argv[1]
        with open(conf_file) as f:
            templates = yaml.safe_load(f)
            include_projects = templates['project']['include']
            exclude_structs = templates['struct']['exclude']
            f.close()

        root_path = sys.argv[2]
        processes = []
        for root, dirs, files in os.walk(root_path):
            # include = False
            # for project in include_projects:
            #     if re.match(r'^.*\/' + project, root) is not None:
            #         include = True
                    # break
            # if include:
            for name in files:
                if re.match(r'.*\.hp?p?$', name) is not None:
                    proc = Process(target=parse_header_file, args=(os.path.join(root, name),))
                    proc.start()
                    processes.append(proc)
                    # parse_header_file(os.path.join(root, name))
        for i in processes:
            i.join()
        # print(datetime.datetime.now())

        compile_commands_file = sys.argv[3]
        with open(compile_commands_file, 'r') as f:
            compile_commands = json.load(f)
        f.close()

        processes = []
        for i in range(0, len(compile_commands)):
            cmd = compile_commands[i]
            proc = Process(target=parse_input_file, args=(cmd, i,))
            proc.start()
            # parse_input_file(cmd, i)
            processes.append(proc)
            i = i + 1

        for i in processes:
            i.join()
        end = datetime.datetime.now()
        print('Exec time: ' + str(end-start))

        print('\nUninitialized params:')

        uninitialized_cnt = 0
        for val in uninitialized:
            match = False
            for i in exclude_structs:
                if re.match(r'' + i, val) is not None:
                    match = True
                    break
            if match:
                continue
            uninitialized_cnt = uninitialized_cnt + 1
            print('\n  struct ' + val)
            for param in uninitialized[val]:
                print('      ' + param)

        subprocess.call('rm temp*', shell=True)
        if uninitialized_cnt > 0:
            exit(1)
        else:
            exit(0)

    except Exception as e:
        print(e)
        exit(1)
