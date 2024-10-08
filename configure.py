'''
    configure
    =========

    Configure icons, stylesheets, and resource files.
'''

__version__ = '0.2.0'

import argparse
import ast
import binascii
import glob
import json
import lzma
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

home_dir = os.path.dirname(os.path.realpath(__file__))
dist_dir = os.path.join(home_dir, 'dist')
resources_dir = os.path.join(home_dir, 'resources')
template_dir = os.path.join(home_dir, 'template')
theme_dir = os.path.join(home_dir, 'theme')
extension_dir = os.path.join(home_dir, 'extension')


def parse_args(argv=None):
    '''Parse the command-line options.'''

    parser = argparse.ArgumentParser(description='Styles to configure for a Qt application.')
    parser.add_argument('-v', '--version', action='version', version=f'%(prog)s {__version__}')
    parser.add_argument(
        '--styles',
        help='comma-separate list of styles to configure. pass `all` to build all themes',
        default='light-blue,dark-blue',
    )
    parser.add_argument(
        '--extensions',
        help='comma-separate list of styles to configure. pass `all` to build all themes',
        default='',
    )
    parser.add_argument(
        '--resource',
        help='output qrc resource file name',
        default='breeze.qrc',
    )
    parser.add_argument(
        '--no-qrc',
        help='do not build QRC resources.',
        action='store_true',
    )
    parser.add_argument(
        '--output-dir',
        help='the default output directory path',
        default=Path(dist_dir),
        type=Path,
    )
    parser.add_argument(
        '--qt-framework',
        help=(
            'target framework to build for. Default = pyqt5. '
            'Note: building for PyQt6 requires PySide6-rcc to be installed.'
        ),
        choices=['pyqt5', 'pyqt6', 'pyside2', 'pyside6'],
        default='pyqt5',
    )
    parser.add_argument(
        '--clean', help='clean dist directory prior to configuring themes.', action='store_true'
    )
    parser.add_argument(
        '--rcc',
        help=(
            'path to the rcc executable. '
            'Overrides rcc of chosen framework. '
            'Only use if system cannot find the rcc exe.'
        ),
    )
    parser.add_argument(
        '--compiled-resource',
        help='output compiled python resource file.',
    )
    parser.add_argument(
        '--use-default-compression',
        help='use the default Qt compression rather than the more efficient custom compression.',
        action='store_true',
    )
    args = parser.parse_args(argv)
    parse_styles(args)
    parse_extensions(args)

    return args


def load_json(path):
    '''Read a JSON file with limited comments support.'''

    # Note: we need comments for maintainability, so we
    # can annotate what works and the rationale, but
    # we don't want to prevent code from working without
    # a complex parser, so we do something very simple:
    # only remove lines starting with '//'.
    with open(path, encoding='utf-8') as file:
        lines = file.read().splitlines()
    lines = [i for i in lines if not i.strip().startswith('//')]
    return json.loads('\n'.join(lines))


def read_template_dir(directory):
    '''Read the template data from a directory'''

    # Make the stylesheet template optional.
    stylesheet = ''
    stylesheet_path = f'{directory}/stylesheet.qss.in'
    if os.path.exists(stylesheet_path):
        with open(f'{directory}/stylesheet.qss.in', encoding='utf-8') as style_file:
            stylesheet = style_file.read()
    data = {
        'stylesheet': stylesheet,
        'icons': [],
    }
    if os.path.exists(f'{directory}/icons.json'):
        icon_data = load_json(f'{directory}/icons.json')
    else:
        icon_data = {}
    for file in glob.glob(f'{directory}/*.svg.in'):
        with open(file, encoding='utf-8') as svg_file:
            svg = svg_file.read()
        name = os.path.splitext(os.path.splitext(os.path.basename(file))[0])[0]
        if name in icon_data:
            replacements = icon_data[name]
        else:
            # Need to find all the values inside the image.
            keys = re.findall(r'\^[0-9a-zA-Z_-]+\^', svg)
            replacements = [i[1:-1] for i in keys]
        data['icons'].append(
            {
                'name': name,
                'svg': svg,
                'replacements': replacements,
            }
        )

    return data


def split_csv(string):
    '''Split a list of values provided as comma-separated values.'''

    values = string.split(',')
    return [i for i in values if i]


def parse_styles(args):
    '''Parse a list of valid styles.'''

    values = split_csv(args.styles)
    if 'all' in values:
        files = glob.glob(f'{theme_dir}/*json')
        values = [os.path.splitext(os.path.basename(i))[0] for i in files]
    args.styles = values


def parse_extensions(args):
    '''Parse a list of valid extensions.'''

    values = split_csv(args.extensions)
    if 'all' in values:
        values = []
        for dirname in os.listdir(extension_dir):
            ext = f'{extension_dir}/{dirname}'
            ext_files = ('stylesheet.qss.in', 'icons.json')
            paths = [f'{ext}/{i}' for i in ext_files]
            if os.path.isdir(ext) and any(os.path.exists(i) for i in paths):
                values.append(dirname)

    args.extensions = values


def parse_hexcolor(color):
    '''Parse a hexadecimal color.'''

    # Have a hex color: can be 6 or 8 (non-standard) items.
    color = color[1:]
    if len(color) not in (6, 8):
        raise NotImplementedError

    red = int(color[:2], 16)
    green = int(color[2:4], 16)
    blue = int(color[4:6], 16)
    alpha = 1.0
    if len(color) == 8:
        alpha = int(color[6:8], 16) / 100
    return (red, green, blue, alpha)


def parse_rgba(color):
    '''Parse an RGBA color.'''

    # Match our rgba character. Note that this is
    # First split the rgba components to get the inner stuff.
    # Both rgb() and rgba() can have or omit an alpha layer.
    rgba = re.match(r'^\s*rgba?\s*\((.*)\)\s*$', color).group(1)
    split = re.split(r'(?:\s*,\s*)|\s+', rgba)
    if len(split) not in (3, 4):
        raise NotImplementedError
    red = int(split[0])
    green = int(split[1])
    blue = int(split[2])
    alpha = 1.0
    if len(split) == 4:
        alpha = float(split[3])
    return (red, green, blue, alpha)


def parse_color(color):
    '''Parse a color into the RGBA components.'''

    if color.startswith('#'):
        return parse_hexcolor(color)
    if color.startswith('rgb'):
        return parse_rgba(color)
    raise NotImplementedError


def icon_basename(icon, extension):
    '''Get the basename for an icon.'''

    if extension == 'default':
        return icon
    return f'{icon}_{extension}'


def replace_by_name(contents, theme, colors=None):
    '''Replace values by color name.'''

    # The placeholders have a syntax like `^foreground^`.
    # To simplify the replacement process, you can specify
    # a limited subset of colors, rather than use all of them.
    if colors is None:
        colors = theme.keys()
    for key in colors:
        color = theme[key]
        contents = contents.replace(f'^{key}^', color)
    return contents


def replace_by_index(contents, theme, colors):
    '''Replace values by color name.'''

    # The placeholders have a syntax like `^0^`, where
    # the is a list of valid colors and the index of
    # the color is the replacement key.
    # This is useful since we can want multiple colors
    # for the same icon (such as hovered arrows).
    for index, key in enumerate(colors):
        sub = f'^{index}^'
        # Need special handle values with opacities. Standard
        # SVG currently does not support `rgba` syntax, with an
        # opacity, but it does provide `fill-opacity` and `stroke-opacity`.
        # Therefore, if the replacement specifies `opacity` or `hex`,
        # parse the color, get the correct value, and use only that
        # for the replacement.
        if key.endswith(':hex'):
            color = theme[key[: -len(':hex')]]
            rgb = [f'{i:02x}' for i in parse_color(color)[:3]]
            value = f'#{"".join(rgb)}'
        elif key.endswith(':opacity'):
            color = theme[key[: -len(':opacity')]]
            value = str(parse_color(color)[3])
        else:
            value = theme[key]
        contents = contents.replace(sub, value)
    return contents


def configure_icons(config, style, qt_dist):
    '''Configure icons for a given style.'''

    theme = config['themes'][style]
    for template in config['templates']:
        for icon in template['icons']:
            replacements = icon['replacements']
            name = icon['name']
            if isinstance(replacements, dict):
                # Then we have the following format:
                #   The key is the substate of the icon, such
                #   as default, hover, pressed, etc, and the value
                #   is an ordered list of replacements.
                for ext, colors in replacements.items():
                    contents = replace_by_index(icon['svg'], theme, colors)
                    filename = f'{qt_dist}/{style}/{icon_basename(name, ext)}.svg'
                    with open(filename, 'w', encoding='utf-8') as file:
                        file.write(contents)
            else:
                # Then we just have a list of replacements for the
                # icon, using standard colors. For example,
                # replacement values might be `^foreground^`.
                assert isinstance(replacements, list)
                contents = replace_by_name(icon['svg'], theme, replacements)
                filename = f'{qt_dist}/{style}/{name}.svg'
                with open(filename, 'w', encoding='utf-8') as file:
                    file.write(contents)


def configure_stylesheet(config, style, qt_dist, style_prefix):
    '''Configure the stylesheet for a given style.'''

    contents = '\n'.join([i['stylesheet'] for i in config['templates']])
    contents = replace_by_name(contents, config['themes'][style])
    contents = contents.replace('^style^', style_prefix)

    with open(f'{qt_dist}/{style}/stylesheet.qss', 'w', encoding='utf-8') as file:
        file.write(contents)


def configure_style(config, style, qt_dist):
    '''Configure the icons and stylesheet for a given style.'''

    def configure_qt(qt_dist, style_prefix):
        os.makedirs(f'{qt_dist}/{style}', exist_ok=True)
        # Need to pass the qt_dist dir.
        configure_icons(config, style, qt_dist)
        configure_stylesheet(config, style, qt_dist, style_prefix)

    # Need to replace the URL paths for loading icons/
    # assets. This uses the resource system, AKA,
    # `url(:/dark/path/to/resource)`.
    if not config['no_qrc']:
        configure_qt(qt_dist, f':/{style}/')


def write_qrc(config, qt_dist):
    '''Simple QRC writer.'''

    # NOTE: We also want to create aliases for light-blue and dark-blue from our
    # light and dark. See:
    #   https://github.com/Alexhuszagh/BreezeStyleSheets/pull/101#issuecomment-2336476041
    resources = []
    for style in config['themes'].keys():
        files = os.listdir(f'{qt_dist}/{style}')
        resources += [f'{style}/{i}' for i in files]
    if 'dark-blue' in config['themes'].keys():
        resources.append('dark/stylesheet.qss')
    if 'light-blue' in config['themes'].keys():
        resources.append('light/stylesheet.qss')

    qrc_path = config['resource']
    if not os.path.isabs(qrc_path):
        qrc_path = f'{qt_dist}/{qrc_path}'
    with open(qrc_path, 'w', encoding='utf-8') as file:
        print('<RCC>', file=file)
        print('  <qresource>', file=file)
        for resource in sorted(resources):
            print(f'    <file>{resource}</file>', file=file)
        print('  </qresource>', file=file)
        print('</RCC>', file=file)


def compile_resource(args):
    '''Compile our resource file to a standalone Python file.'''

    rcc = parse_rcc(args)
    resource_path = args.resource
    compiled_resource_path = args.compiled_resource
    if not os.path.isabs(resource_path):
        resource_path = f'{args.output_dir}/{resource_path}'
    if not os.path.isabs(compiled_resource_path):
        compiled_resource_path = f'{resources_dir}/{compiled_resource_path}'

    command = [rcc, resource_path, '-o', compiled_resource_path]
    if not args.use_default_compression:
        command.append('-no-compress')
    try:
        subprocess.check_output(
            command,
            stdin=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            shell=False,
        )
    except subprocess.CalledProcessError as error:
        if b'File does not exist' in error.stderr:
            print('ERROR: Ensure qrc file exists or deselect "no-qrc" option!', file=sys.stderr)
        else:
            print(f'ERROR: Got an unknown error of "{error.stderr.decode("utf-8")}"!', file=sys.stderr)
        raise SystemExit from error
    except FileNotFoundError as error:
        if args.rcc:
            print('ERROR: rcc path invalid!', file=sys.stderr)
        else:
            print('ERROR: Ensure rcc executable exists for chosen framework!', file=sys.stderr)
        print(
            'Required rcc for PyQt5: pyrcc5',
            'Required rcc for PySide6 & PyQt6: PySide6-rcc',
            'Required rcc for PySide2: PySide2-rcc',
            '',
            'if using venv, activate it or provide path to rcc.',
            sep='\n',
            file=sys.stderr,
        )
        raise SystemExit from error

    if args.qt_framework == 'pyqt6':
        fix_qt6_import(compiled_resource_path)

    if not args.use_default_compression:
        compress_resource(compiled_resource_path)


def compress(data):
    '''Compress an array to a smaller amount, and then split it along lines.'''
    raise NotImplementedError('TODO')


def compress_and_replace(module, prefix):
    '''Extract data from a resource module, then replace the data with compress values.'''

    # first, get and compress our data
    # this pattern is always safe since there will never be any internal `"`
    # characters due to how compilation/quoting is done, even escaped ones.
    pattern = fr'(?P<prefix>{prefix}\s*=\s*)(?P<data>b".*?")'
    match = re.search(pattern, module, flags=re.DOTALL)
    if match is None and prefix == 'qt_resource_struct':
        # NOTE: some older versions use v1/v2 structs
        v1 = compress_and_replace(module, 'qt_resource_struct_v1')
        v2 = compress_and_replace(v1, 'qt_resource_struct_v2')
        return v2
    decompressed = ast.literal_eval(match.group('data'))
    compressed = lzma.compress(decompressed)

    # NOTE: to avoid any issues with `"` or `'` characters, we always escape it
    hexlified = binascii.hexlify(compressed).decode('ascii').upper()
    escaped = ''.join([f'\\x{hexlified[i:i+2]}' for i in range(0, len(hexlified), 2)])
    lzma_replace = f'{prefix} = lzma.decompress(_{prefix})'
    replacement = f'_{prefix} = b"{escaped}"\n{lzma_replace}\n'

    return module[: match.start()] + replacement + module[match.end() + 1 :]


def compress_resource(path):
    '''Compress the data within a Qt resource module.'''

    # want to minimize the file size, let's use custom gzip compression
    with open(path, encoding='utf-8') as file:
        module = file.read()
    module = module.replace('import QtCore', 'import QtCore\nimport lzma', 1)
    # NOTE: these should never be none or we have an error
    module = compress_and_replace(module, 'qt_resource_data')
    module = compress_and_replace(module, 'qt_resource_name')
    module = compress_and_replace(module, 'qt_resource_struct')

    with open(path, 'w', encoding='utf-8') as file:
        file.write(module)


def configure(args):
    '''Configure all styles and write the files to a QRC file.'''

    if args.clean:
        shutil.rmtree(args.output_dir, ignore_errors=True)

    # Need to convert our styles accordingly.
    config = {'themes': {}, 'templates': [], 'no_qrc': args.no_qrc, 'resource': args.resource}
    config['templates'].append(read_template_dir(template_dir))
    for style in args.styles:
        config['themes'][style] = load_json(f'{theme_dir}/{style}.json')
    for extension in args.extensions:
        config['templates'].append(read_template_dir(f'{extension_dir}/{extension}'))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for style in config['themes']:
        configure_style(config, style, str(args.output_dir))

    # Create aliases for our light-blue and dark-blue styles to light and dark.
    # Only create aliases if light-blue and/or dark-blue are to be built.
    aliases = set(args.styles) & {'dark-blue', 'light-blue'}
    for theme in aliases:
        source = args.output_dir / theme / 'stylesheet.qss'
        destination = args.output_dir / theme.split('-')[0] / 'stylesheet.qss'
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(source, destination)

    # Create and compile our resource files.
    if not args.no_qrc:
        write_qrc(config, str(args.output_dir))
    if args.compiled_resource is not None:
        compile_resource(args)


def fix_qt6_import(compiled_file):
    '''Fix import after using PySide6-rcc to compile for PyQt6'''

    with open(compiled_file, 'r', encoding='utf-8') as file:
        text = file.read()
    text = text.replace('PySide6', 'PyQt6', 1)
    with open(compiled_file, 'w', encoding='utf-8') as file:
        file.write(text)


def parse_rcc(args):
    '''Get rcc required for chosen framework'''

    if args.rcc:
        return args.rcc
    if args.qt_framework in ('pyqt6', 'pyside6'):
        return 'pyside6-rcc'
    if args.qt_framework == 'pyqt5':
        return 'pyrcc5'
    if args.qt_framework == 'pyside2':
        return 'pyside2-rcc'

    raise ValueError(f'Got an unsupported Qt framework of "{args.qt_framework}".')


def main(argv=None):
    '''Configuration entry point'''
    configure(parse_args(argv))


if __name__ == '__main__':
    sys.exit(main())
