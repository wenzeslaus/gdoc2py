#!/usr/bin/python

"""


(C) 2016-2020 by Vaclav Petras

This program is free software under the GNU General Public License
(>=v2). Read the file LICENSE for details.
"""


import nbformat as nbf
from nbformat import v4 as nb
import sys
import argparse
from html.parser import HTMLParser
from html.entities import name2codepoint
import shlex
import re
import keyword

ignored_lines = [
    # re.compile(r'grass70'),
    re.compile(r"cd"),
    re.compile(r"cd.*"),
    # re.compile(r'\s*d\.mon'),
    # re.compile(r'\s*d\.out.file')
]

line_count = 0

common_replacements = [
    (re.compile("&gt;"), ">"),
    (re.compile("&lt;"), "<"),
    (re.compile("&amp;"), "&"),
]

# allow also uppper case tags for now
text_replacemets = [
    (re.compile(r"<p>", re.IGNORECASE), ""),
    (re.compile(r"</p>", re.IGNORECASE), ""),
    (re.compile(r"<br>", re.IGNORECASE), ""),
    (re.compile(r"<div>", re.IGNORECASE), ""),
    (re.compile(r"</div>", re.IGNORECASE), ""),
    (re.compile(r'<a href="([^"]+)">[^<]+</a>', re.IGNORECASE), r"\1"),
    (re.compile(r"^\s+\n$", re.IGNORECASE), "\n"),
]

text_replacemets.extend(common_replacements)

file_path_extraction = re.compile(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', re.IGNORECASE)
file_from_url_extraction = re.compile(
    r'<a href="([^"]+)/([^"/]+)"[^>]*>([^<]+)</a>', re.IGNORECASE
)
download_attribute_presence = re.compile(
    r'<a href="([^"]+)"[^>]* download[^>]*>([^<]+)</a>', re.IGNORECASE
)

code_replacemets = [
    #    (re.compile('d.mon wx.'), 'd.mon cairo'),
    #    (re.compile('d.out.file (.+)(.png|)'),
    #     r"# save the currently rendered image (generated replacement of d.out.file)"
    #      "\ncp map.png \1.png"),
]

# code_replacemets.extend(common_replacements)

d_command = re.compile(r"d\..+ .+")


class Module(object):
    def __init__(self):
        self.name = None
        self.options = []  # as list to preserve order
        self.flags = ""
        self.long_flags = []
        self.first_option = None
        self.original_string = None

    def uses_option(self, name):
        return name in [key for key, value in self.options]

    # TODO: implement AND and OR relation, now only OR
    def uses_options(self, names):
        keys = [key for key, value in self.options]
        for name in names:
            if name in keys:
                return True
        return False


def string_to_module(string):
    module = Module()
    try:
        tokens = shlex.split(string)
    except ValueError as error:
        raise ValueError("Cannot parse using shell rules (%s): %s" % (error, string))
    module.name = tokens[0]
    module.original_string = string
    for i, token in enumerate(tokens[1:]):
        match = re.search("^([a-z_0-9]+)=(.*)", token)
        if match:
            key = match.group(1)
            value = match.group(2)
            module.options.append((key, value))
            continue
        match = re.search("^-([a-zA-Z0-9]+)", token)
        if match:
            # flag or flags
            flag = match.group(1)
            module.flags += flag
            continue
        match = re.search("^--([a-zA-Z0-9_]+)", token)
        if match:
            flag = match.group(1)
            module.long_flags.append(flag)
            continue
        if not module.options:
            module.first_option = token
    return module


def module_to_python(module):
    first_option_usable = False
    if module.first_option:
        if module.name in ["r.mapcalc"]:
            first_option_usable = True
        else:
            # this is just guessing, only safe way is the fallback
            if module.uses_options(("output", "out")):
                # TODO: do not modify function input
                module.options.insert(0, ("input", module.first_option))
            elif module.name == "g.region":
                module.options.insert(0, ("region", module.first_option))
            elif module.name == "d.legend":
                module.options.insert(0, ("raster", module.first_option))
            elif module.name == "r.stats":  # r.stats has optional output
                module.options.insert(0, ("input", module.first_option))
            elif module.name.startswith(("d.", "r.", "v.")) and module.name not in [
                "d.out.file"
            ]:
                # TODO: do not modify function input
                module.options.insert(0, ("map", module.first_option))
            # elif module.name.startswith('d.'):
            #    # TODO: do not modify function input
            #    module.options.insert(0, ('map', module.first_option))
            # elif module.name.startswith('r.'):
            #    # TODO: do not modify function input
            #    module.options.insert(0, ('input', module.first_option))
            else:
                return (
                    "# execute manually the following or its equivalent:\n# %s"
                    % module.original_string
                )

    is_reading = False
    if (
        module.name in ["r.category", "r.report"]
        or (module.name == "v.info" and "g" not in module.flags)
        or (module.name == "r.stats" and not module.uses_option("output"))
    ):
        is_reading = True

    if first_option_usable:
        # TODO: support r3.mapcalc
        value = module.first_option
        quote = '"'
        if '"' in value:
            quote = "'"
        elif "'" in value:
            quote = '"'
        string = "gs.mapcalc(%s%s%s" % (quote, value, quote)
    elif (
        module.name in ["r.info", "r.univar", "v.univar"]
        or (module.name == "v.info" and "c" not in module.flags)
        or (module.name == "g.region" and ("p" in module.flags or "g" in module.flags))
    ):
        if "g" not in module.flags:
            # TODO: do not modify function input
            module.flags += "g"
        string = "gs.parse_command('%s'" % module.name
    elif is_reading:
        string = "print(gs.read_command('%s'" % module.name
    else:
        string = "gs.run_command('%s'" % module.name

    for key, value in module.options:
        # TODO: customize preferred quote
        quote = '"'
        if '"' in value:
            quote = "'"
        elif "'" in value:
            quote = '"'
        if key in keyword.kwlist:
            key += "_"
        string += ", %s=%s%s%s" % (key, quote, value, quote)

    if module.flags:
        string += ", flags='%s'" % module.flags

    for flag in module.long_flags:
        string += ", %s=True" % (flag)
    string += ")"
    if is_reading:
        # close print call
        string += ")"
    return string


JUPYTER_INTRODUCTION_CODE = """\
# This is a quick introduction into Jupyter Notebook.
# Python code can be executed like this:
a = 6
b = 7
c = a * b
print("Answer is", c)
# Python code can be mixed with command line code (Bash).
# It is enough just to prefix the command line with an exclamation mark:
!echo "Answer is $c"
# Use Shift+Enter to execute this cell. The result is below.
"""

GRASS_START_CODE = """\
import os
import sys
import subprocess
from IPython.display import Image

# create GRASS GIS runtime environment
gisbase = subprocess.check_output(["{grass}", "--config", "path"]{extra}).strip()
os.environ['GISBASE'] = gisbase
sys.path.append(os.path.join(gisbase, "etc", "python"))

# do GRASS GIS imports
import grass.script as gs
import grass.script.setup as gsetup

# set GRASS GIS session data
rcfile = gsetup.init(gisbase, "{gisdbase}", "{location}", "{mapset}")
"""

GRASS_SETTINGS_CODE = """\
# default font displays
os.environ['GRASS_FONT'] = 'sans'
# overwrite existing maps
os.environ['GRASS_OVERWRITE'] = '1'
gs.set_raise_on_error(True)
gs.set_capture_stderr(True)
"""

GRASS_START_DISPLAY_CODE = """\
# set display modules to render into a file (named map.png by default)
os.environ['GRASS_RENDER_IMMEDIATE'] = 'cairo'
os.environ['GRASS_RENDER_FILE_READ'] = 'TRUE'
os.environ['GRASS_LEGEND_FILE'] = 'legend.txt'
"""
# gs.run_command('d.mon', start='cairo')


def start_of_grass_session(string, grass, gisdbase, location, mapset, python2=False):
    if python2:
        extra = ""
    else:
        extra = ", text=True"
    return [
        JUPYTER_INTRODUCTION_CODE.strip(),
        GRASS_START_CODE.strip().format(
            grass=grass,
            gisdbase=gisdbase,
            location=location,
            mapset=mapset,
            extra=extra,
        ),
        GRASS_SETTINGS_CODE.strip(),
        GRASS_START_DISPLAY_CODE.strip(),
    ]


# TODO: refactor the following 4 functions
def bash_to_python(string):
    output = []
    prev_line = ""
    d_command_present = False
    last_command = None
    for line in string.splitlines():
        if line:
            if line.endswith("\\"):
                prev_line += line + "\n"
                continue
            elif prev_line:
                line = prev_line + line
                prev_line = ""
            module = string_to_module(line)
            # TODO: potentially split to cells when d.out.file
            if module.name == "d.out.file":
                output.append('Image(filename="map.png")')
            else:
                output.append(module_to_python(module))
                if module.name.startswith("d."):
                    d_command_present = True
            last_command = module.name
        else:
            output.append("\n")
    if d_command_present and last_command != "d.out.file":
        output.append('Image(filename="map.png")')
    return ["\n".join(output)]


def bash_to_pure_bash_cells(string):
    """Create cells for pure Bash notebook (with Bash kernel)"""
    # TODO: share code with the function below
    # TODO: preserve syntax more while still handling d.out.file
    cells = []
    output = []
    prev_line = ""
    d_command_present = False
    last_command = None
    for line in string.splitlines():
        if line:
            if line.endswith("\\"):
                prev_line += line + "\n"
                continue
            elif prev_line:
                line = prev_line + line
                prev_line = ""
            # TODO: potentially split to cells when d.out.file
            if line.startswith("d.out.file"):
                cells.append("\n".join(output))
                # pseudo cell magic to be replaced later
                output = ["%%markdown", "![image](map.png)"]
                cells.append("\n".join(output))
                output = []
            else:
                output.append(line)
                if line.startswith("d."):
                    d_command_present = True
            last_command = line
        else:
            output.append("\n")
    if output:
        cells.append("\n".join(output))
    if d_command_present and not last_command.startswith("d.out.file"):
        cells.append("\n".join(["%%markdown", "![image](map.png)"]))
    return cells


def bash_to_cells(string):
    r"""Create cells for a Python notebook using %%bash cell magic

    >>> bash_to_cells("ls")
    ['%%bash\nls']

    >>> bash_to_cells("ls -la\nls -la")
    ['%%bash\nls -la\nls -la']

    >>> t = "g.region raster=elevation\nr.univar elevation\nd.rast elevation"
    >>> cells = bash_to_cells(t)
    >>> type(cells)
    <type 'list'>
    >>> len(cells)
    2
    >>> print(cells[0])
    %%bash
    g.region raster=elevation
    r.univar elevation
    d.rast elevation
    >>> print(cells[1])
    Image(filename="map.png")

    """
    # TODO: preserve syntax more while still handling d.out.file
    cells = []
    output = ["%%bash"]
    prev_line = ""
    d_command_present = False
    last_command = None
    for line in string.splitlines():
        if line:
            if line.endswith("\\"):
                prev_line += line + "\n"
                continue
            elif prev_line:
                line = prev_line + line
                prev_line = ""
            # TODO: potentially split to cells when d.out.file
            if line.startswith("d.out.file"):
                cells.append("\n".join(output))
                cells.append('Image(filename="map.png")')
                output = ["%%bash"]
            else:
                output.append(line)
                if line.startswith("d."):
                    d_command_present = True
            last_command = line
        else:
            output.append("\n")
    if len(output) > 1:
        cells.append("\n".join(output))
    if d_command_present and not last_command.startswith("d.out.file"):
        cells.append('Image(filename="map.png")')
    return cells


def bash_to_exclamations(string):
    """Create cells for a Python notebook using exclamation mark"""
    # the ! syntax is limited just to simple commands
    # TODO: but pipe is supported as long as it is in one line
    output = []
    prev_line = ""
    d_command_present = False
    last_command = None
    for line in string.splitlines():
        if line:
            if line.endswith("\\"):
                prev_line += line + "\n"
                continue
            elif prev_line:
                line = prev_line + line
                prev_line = ""
            module = string_to_module(line)
            # TODO: potentially split to cells when d.out.file
            if line.startswith("d.out.file"):
                output.append('Image(filename="map.png")')
            else:
                # exclamations support continued lines with backslash
                output.append("!" + line)
                if module.name.startswith("d."):
                    d_command_present = True
            last_command = module.name
        else:
            output.append("\n")
    if d_command_present and last_command != "d.out.file":
        output.append('Image(filename="map.png")')
    return ["\n".join(output)]


class DummyProcessor(object):
    def __getattr__(self, name):
        class Attr(object):
            def __init__(self, name):
                self._name = name

            def __call__(self, *args, **kwargs):
                output = self._name
                for arg in args:
                    if arg:
                        output += " " + arg
                for key, value in kwargs.items():
                    output += " %s=%s" % (key, value)
                # print(output)

        return Attr(name)


# first split document into
# blocks/cells of code and text and than convert each of the items
class Splitter(object):
    r"""

    >>> t = "<h2>Display</h2>\n\n<pre><code>\nd.rast elevation\n</code></pre>\n\nAnd that's it.\n"
    >>> p = Processor()
    >>> s = Splitter(p)
    >>> s.split(t)
    >>> p.finish()
    >>> len(p.blocks)
    3
    >>> p.blocks[0]['block_type']
    'text'
    >>> p.blocks[0]['content']
    ['<h2>Display</h2>', '']
    >>> p.blocks[2]['content']
    ['', "And that's it."]

    >>> t2 = "Display\n\n<!--\n<pre><code>\nd.erase\n</code></pre>\n-->\n\nEnd.\n"
    >>> p = Processor()
    >>> s = Splitter(p)
    >>> s.split(t2)
    >>> p.finish()
    >>> len(p.blocks)
    1
    >>> p.blocks[0]['block_type']
    'text'
    >>> print("\n".join(p.blocks[0]['content']))
    Display
    <BLANKLINE>
    <!--
    <pre><code>
    d.erase
    </code></pre>
    -->
    <BLANKLINE>
    End.

    >>> t2 = "Text.\n<pre data-run=\"no\"><code>\nd.legend\n</code></pre>\nText.\n"
    >>> p = Processor()
    >>> s = Splitter(p)
    >>> s.split(t2)
    >>> p.finish()
    >>> len(p.blocks)
    1
    >>> p.blocks[0]['block_type']
    'text'
    >>> print("\n".join(p.blocks[0]['content']))
    Text.
    <pre data-run="no"><code>
    d.legend
    </code></pre>
    Text.

    >>> t2 = "Text.\n<pre data-run=\"no\"><code>\nd.legend\n</code></pre>\nText.\n"
    >>> p = Processor()
    >>> s = Splitter(p)
    >>> s.split(t2)
    >>> p.finish()
    >>> len(p.blocks)
    1
    >>> p.blocks[0]['block_type']
    'text'
    >>> print("\n".join(p.blocks[0]['content']))
    Text.
    <pre data-run="no"><code>
    d.legend
    </code></pre>
    Text.

    >>> s = Splitter(DummyProcessor())
    >>> s.split(t)
    add_text <h2>Display</h2>
    add_text
    start_code <pre><code>
    add_code d.rast elevation
    end_code </code></pre>
    add_text
    add_text And that's it.

    >>> t3 = "Text.\n<pre data-filename=\"mycolor.txt\">\n50 blue\n70 aqua\n</pre>\nText."
    >>> s = Splitter(DummyProcessor())
    >>> s.split(t3)
    add_text Text.
    start_file_content <pre data-filename="mycolor.txt">
    add_file_content 50 blue
    add_file_content 70 aqua
    end_file_content </pre>
    add_text Text.

    """  # noqa: E501

    def __init__(self, processor, code_tags=None):
        assert len(code_tags) == 2
        self.processor = processor
        self.code_start = re.compile(code_tags[0])
        self.code_end = re.compile(code_tags[1])
        self.file_content_start = re.compile(r"^<pre data-filename=.*>$")
        self.file_content_end = re.compile(r"^</pre>$")
        self.comment_start = re.compile(r"^\s*<!--")
        self.comment_end = re.compile(r"-->\s*$")
        self.in_code = False
        self.in_file_content = False
        self.in_block_comment = False

    def split(self, text):
        for line in text.splitlines():
            if self.file_content_start.search(line) and not self.in_block_comment:
                self.in_file_content = True
                self.processor.start_file_content(line)
                continue
            elif self.in_file_content and self.file_content_end.search(line):
                self.in_file_content = False
                self.processor.end_file_content(line)
                continue
            elif self.code_start.search(line) and not self.in_block_comment:
                self.in_code = True
                self.processor.start_code(line)
                continue
            elif self.in_code and self.code_end.search(line):
                self.in_code = False
                self.processor.end_code(line)
                continue
            elif self.comment_start.search(line) and not self.comment_end.search(line):
                self.in_block_comment = True
            elif self.in_block_comment and self.comment_end.search(line):
                self.in_block_comment = False
            if self.in_code:
                self.processor.add_code(line)
            elif self.in_file_content:
                self.processor.add_file_content(line)
            else:
                self.processor.add_text(line)


class Processor(object):
    """

    >>> p = Processor()
    >>> p.start_code('')
    >>> p.add_code('g.region raster=elevation')
    >>> p.add_code('r.surf.fractal output=fractals')
    >>> p.add_code('d.rast fractals')
    >>> p.add_code('d.legend fractals')
    >>> p.end_code('')
    >>> p.blocks[0]['block_type']
    'code'
    >>> p.blocks[0]['content']
    ['g.region raster=elevation', 'r.surf.fractal output=fractals', 'd.rast fractals', 'd.legend fractals']

    >>> p.start_text('')
    >>> p.add_text('Some text')
    >>> p.end_text('')
    >>> len(p.blocks)
    2
    >>> p.blocks[0]['block_type']
    'code'
    >>> p.blocks[1]['block_type']
    'text'

    """  # noqa: E501

    def __init__(self):
        self._current_code = None
        self._current_file_content = None
        self._current_text = None
        self._blocks = []

        # text is background content
        self.start_text()

        self.filename_capture = re.compile(r'<pre data-filename="(.*?)">')

    @property
    def blocks(self):
        """"""
        return self._blocks

    def finish(self):
        if self._current_text:
            self.end_text()

    def add_block(self, block_type, content, attrs=None):
        block = {"block_type": block_type, "content": content}
        if attrs:
            block["attrs"] = attrs
        self._blocks.append(block)

    def start_text(self, text=None):
        self._current_text = []

    def add_text(self, text):
        if self._current_text is None:
            raise RuntimeError("Text block is not active at: %s" % text)
        self._current_text.append(text)

    def end_text(self, text=None):
        # empty text blocks are ignored
        if not self._current_text or not any(self._current_text):
            self._current_text = None
            return
        self.add_block(block_type="text", content=self._current_text)
        self._current_text = None

    def start_code(self, text=None):
        self.end_text()
        self._current_code = []

    def add_code(self, text):
        self._current_code.append(text)

    def end_code(self, text=None):
        self.add_block(block_type="code", content=self._current_code)
        self._current_code = None
        self.start_text()

    def start_file_content(self, text=None):
        self.end_text()
        self._current_file_content = []

        if text:
            match = self.filename_capture.search(text)
            if match:
                self._current_filename = match.group(1)
        if not self._current_filename:
            raise ValueError("File name needed for the file content (%s)" % text)

    def add_file_content(self, text):
        self._current_file_content.append(text)

    def end_file_content(self, text=None):
        attrs = {"filename": self._current_filename}
        self.add_block(
            block_type="file_content", content=self._current_file_content, attrs=attrs
        )
        self.start_text()


class HTMLBashCodeToPythonNotebookConverter(HTMLParser):
    r"""

    >>> n = nb.new_notebook()
    >>> c = HTMLBashCodeToPythonNotebookConverter(n)
    >>> c.feed("g.region raster=elevation\n<!-- d.erase -->\nd.rast elevation")
    >>> c.finish()
    >>> len(n['cells'])
    1
    >>> print(n['cells'][0]['source'])
    gs.run_command('g.region', raster="elevation")
    gs.run_command('d.erase')
    gs.run_command('d.rast', map="elevation")
    Image(filename="map.png")

    """

    def __init__(
        self,
        notebook,
        grass=None,
        gisdbase=None,
        location=None,
        mapset=None,
        python2=False,
    ):
        HTMLParser.__init__(self)

        self.nb = notebook
        self.data = ""

        self.grass = grass
        self.gisdbase = gisdbase
        self.location = location
        self.mapset = mapset

        self.python2 = python2

    def handle_data(self, data):
        self.data += data

    def handle_entityref(self, name):
        c = chr(name2codepoint[name])
        self.data += c

    def handle_comment(self, data):
        if data.strip().startswith("d.erase"):
            self.data += data.strip()

    def finish(self):
        cell = ""
        for line in self.data.splitlines():
            line = re.sub("<!--.*-->", "", line)
            skip_line = False
            for ignored_line in ignored_lines:
                if ignored_line.search(line):
                    skip_line = True
            if not skip_line:
                for regexp, replacement in code_replacemets:
                    line = regexp.sub(replacement, line)
                if line:
                    cell += line + "\n"
        if re.search("^grass.?.?$", cell):
            cells = start_of_grass_session(
                cell,
                self.grass,
                self.gisdbase,
                self.location,
                self.mapset,
                python2=self.python2,
            )
        else:
            cells = bash_to_python(cell.strip())
        for cell in cells:
            self.nb["cells"].append(nb.new_code_cell(cell))
        self.data = ""


class HTMLBashCodeToNotebookConverter(HTMLParser):
    r"""

    >>> t = "g.region raster=elevation\nr.univar elevation\nd.rast elevation"
    >>> n = nb.new_notebook()
    >>> c = HTMLBashCodeToNotebookConverter(n)
    >>> c.feed(t)
    >>> c.finish()
    >>> len(n['cells'])
    1
    >>> print(n['cells'][0]['source'])
    !g.region raster=elevation
    !r.univar elevation
    !d.rast elevation
    Image(filename="map.png")

    >>> n = nb.new_notebook()
    >>> c = HTMLBashCodeToNotebookConverter(n, syntax='cell')
    >>> c.feed(t)
    >>> c.finish()
    >>> len(n['cells'])
    2
    >>> print(n['cells'][0]['source'])
    %%bash
    g.region raster=elevation
    r.univar elevation
    d.rast elevation
    >>> print(n['cells'][1]['source'])
    Image(filename="map.png")

    >>> n = nb.new_notebook()
    >>> c = HTMLBashCodeToNotebookConverter(n, syntax='pure')
    >>> c.feed(t)
    >>> c.finish()
    >>> len(n['cells'])
    2
    >>> print(n['cells'][0]['source'])
    g.region raster=elevation
    r.univar elevation
    d.rast elevation
    >>> print(n['cells'][1]['source'])  # pseudo cell magic
    %%markdown
    ![image](map.png)

    """

    def __init__(
        self,
        notebook,
        syntax="!",
        grass=None,
        gisdbase=None,
        location=None,
        mapset=None,
    ):
        HTMLParser.__init__(self)

        if syntax not in ("pure", "cell", "!"):
            raise ValueError("Requested output syntax not recognized")
        self._syntax = syntax

        self.nb = notebook
        self.data = ""

        self.grass = grass
        self.gisdbase = gisdbase
        self.location = location
        self.mapset = mapset

    def handle_data(self, data):
        self.data += data

    def handle_entityref(self, name):
        c = chr(name2codepoint[name])
        self.data += c

    def handle_comment(self, data):
        if data.strip().startswith("d.erase"):
            self.data += data.strip()

    def finish(self):
        cell = ""
        for line in self.data.splitlines():
            line = re.sub("<!--.*-->", "", line)
            skip_line = False
            for ignored_line in ignored_lines:
                if ignored_line.search(line):
                    skip_line = True
            if not skip_line:
                for regexp, replacement in code_replacemets:
                    line = regexp.sub(replacement, line)
                if line:
                    cell += line + "\n"
        if re.search("^grass.?.?$", cell):
            cells = start_of_grass_session(
                cell, self.grass, self.gisdbase, self.location, self.mapset
            )
            # TODO: the env vars need to be in bash for the pure bash
            cells = [
                "# using Python to initialize GRASS GIS\n" + cell for cell in cells
            ]
        else:
            if self._syntax == "pure":
                cells = bash_to_pure_bash_cells(cell.strip())
            elif self._syntax == "cell":
                cells = bash_to_cells(cell.strip())
            else:
                cells = bash_to_exclamations(cell.strip())
        for cell in cells:
            # TODO: deal with the pseudo cell magic %%markdown cells
            self.nb["cells"].append(nb.new_code_cell(cell))
        self.data = ""


class HTMLFileContentToPythonNotebookConverter(HTMLParser):
    r"""

    >>> n = nb.new_notebook()
    >>> c = HTMLFileContentToPythonNotebookConverter(n, filename="test.txt")
    >>> c.feed("50 blue\n70 aqua\n")
    >>> c.finish()
    >>> len(n['cells'])
    1
    >>> print(n['cells'][0]['source'])
    %%file test.txt
    50 blue
    70 aqua

    """

    def __init__(self, notebook, filename):
        HTMLParser.__init__(self)

        self.nb = notebook
        self.filename = filename
        self.data = ""

    def handle_data(self, data):
        self.data += data

    def handle_entityref(self, name):
        c = chr(name2codepoint[name])
        self.data += c

    def finish(self):
        cell = ""
        # process pre content as file
        cell = "%%%%file %s\n%s" % (self.filename, self.data.strip())
        self.nb["cells"].append(nb.new_code_cell(cell))
        self.data = ""


class HTMLToMarkdownNotebookConverter(HTMLParser):
    r"""

    >>> n = nb.new_notebook()
    >>> c = HTMLToMarkdownNotebookConverter(n)
    >>> c.feed("Text.\n<pre>\nPre-formatted.\n</pre>\nText.")
    >>> c.finish()
    >>> print(n['cells'][0]['source'])
    Text.
    ```
    Pre-formatted.
    ```
    Text.

    >>> n = nb.new_notebook()
    >>> c = HTMLToMarkdownNotebookConverter(n)
    >>> c.feed("Text.\n<pre data-run=\"no\"><code>\nd.legend\n</code></pre>\nText.")
    >>> c.finish()
    >>> print(n['cells'][0]['source'])
    Text.
    ```
    d.legend
    ```
    Text.
    """

    def __init__(self, notebook):
        HTMLParser.__init__(self)

        self.in_pre = False

        self.nb = notebook
        self.data = ""
        # used to carry hyperlink data
        self.link_url = None
        # used to carry hyperlink data
        self.link_url = None

        self.download_files = []

    def finish(self):
        # process text
        cell = self.data.strip()
        if cell:
            self.nb["cells"].append(nb.new_markdown_cell(cell))
            self.data = ""

    def handle_starttag(self, tag, attrs):
        if re.search(r"^h(\d)$", tag):
            # TODO: check std heading syntax
            nchars = int(tag[1])
            self.data += "#" * nchars + " "
        elif tag == "li":
            if self.data[-1] != "\n":
                self.data += "\n"
            self.data += "* "
        elif tag == "em":
            # TODO: more robust test
            # TODO: list to module
            # if 'class' in attrs and 'module' in attrs['class']:
            self.data += "_"
        elif tag == "a":
            self.data += "["
            # possibly just store last tag attrs
            for key, value in attrs:
                if key == "href":
                    self.link_url = value
                    break
        elif tag == "code" and not self.in_pre:
            self.data += "`"
        elif tag == "pre":
            self.in_pre = True
            self.data += "```"
        # elif tag == 'blockquote':
        #    self.data += '\n\n\t'

    def handle_endtag(self, tag):
        # if tag == 'blockquote':
        #     self.data += "\n\n"
        if tag == "em":
            self.data += "_"
        elif tag == "a":
            # TODO: URLs need adding
            # http://ncsu-geoforall-lab.github.io/geospatial-modeling-course/grass/
            # if any relative (as in ../ etc., not just data/)
            self.data += "](%s)" % self.link_url
            if self.link_url.startswith("data/"):
                self.download_files.append(
                    # URL-only lines should be ignored automatically
                    "http://ncsu-geoforall-lab.github.io/geospatial-modeling-course/grass/"  # noqa: E501
                    + self.link_url
                )
            self.link_url = None
        elif tag == "pre":
            self.data += "```"
            self.in_pre = False
        elif tag == "code" and not self.in_pre:
            self.data += "`"

    def handle_data(self, data):
        self.data += data

    def handle_entityref(self, name):
        if name == "ndash":
            self.data += "--"
        else:
            c = chr(name2codepoint[name])
            self.data += c


def add_file_downloads(notebook, filenames, python2):
    cell = "# a proper directory is already set, download files\n"
    if python2:
        cell += "import urllib\n"
    else:
        cell += "import urllib.request\n"
    for filename in filenames:
        name = filename.split("/")[-1]
        if python2:
            cell += 'urllib.urlretrieve("%s", "%s")\n' % (filename, name)
        else:
            cell += 'urllib.request.urlretrieve("%s", "%s")\n' % (filename, name)
    cell = cell.strip()
    download_text_index = None
    for i, existing_cell in enumerate(notebook["cells"]):
        if existing_cell.source.startswith("Download all text files"):
            download_text_index = i
            break
    if download_text_index is None:
        # TODO: better guess than 2?
        notebook["cells"].insert(2, nb.new_code_cell(cell))
    else:
        # insert before
        notebook["cells"].insert(download_text_index, nb.new_code_cell(cell))
        if not notebook["cells"][download_text_index - 1].source:
            del notebook["cells"][download_text_index - 1]


def finish_session(notebook):
    code = "# end the GRASS session\nos.remove(rcfile)"
    notebook["cells"].append(nb.new_code_cell(code))


def main():
    parser = argparse.ArgumentParser(
        description="Convert HTML documentation to Jupyter Notebook."
    )
    parser.add_argument("files", metavar="FILE", nargs="+", help="Files to convert")
    parser.add_argument(
        "--lang",
        dest="lang",
        default="python",
        choices=["python", "python2", "bash", "bash-cells", "pure-bash"],
        help="GRASS GIS executable",
    )
    # TODO: allow no provided
    # TODO: allow mapset as full path
    parser.add_argument(
        "--grass", dest="grass", default="grass", help="GRASS GIS executable"
    )
    parser.add_argument(
        "--gisdbase", dest="gisdbase", required=True, help="GRASS GIS Database"
    )
    parser.add_argument(
        "--location", dest="location", required=True, help="GRASS GIS Location"
    )
    parser.add_argument(
        "--mapset", dest="mapset", required=True, help="GRASS GIS Mapset"
    )
    parser.add_argument(
        "--code-start",
        dest="code_start",
        default=r"^<pre><code>$",
        help="Starting tags of a code block (regular expression)",
    )
    parser.add_argument(
        "--code-end",
        dest="code_end",
        default=r"^</code></pre>$",
        help="Ending tags of a code block (regular expression)",
    )
    parser.add_argument(
        "--session-after-first-text",
        dest="session_after_text",
        action="store_true",
        help="Place a GRASS GIS session code after first text cell",
    )
    args = parser.parse_args()
    input_ = args.files[0]
    output = args.files[1]

    lang = args.lang

    processor = Processor()
    splitter = Splitter(processor, code_tags=(args.code_start, args.code_end))
    splitter.split(open(input_).read())
    processor.finish()

    notebook = nb.new_notebook()
    if lang == "python2":
        notebook["metadata"]["kernelspec"] = {
            "display_name": "Python 2",
            "language": "python",
            "name": "python2",
        }
    else:
        notebook["metadata"]["kernelspec"] = {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        }

    filenames = []

    add_session_start = False
    first_text_cell = True

    for block in processor.blocks:
        if add_session_start:
            add_session_start = False
            cells = start_of_grass_session(
                "",
                grass=args.grass,
                gisdbase=args.gisdbase,
                location=args.location,
                mapset=args.mapset,
                python2=lang == "python2",
            )
            for cell in cells:
                notebook["cells"].append(nb.new_code_cell(cell))
        if block["block_type"] == "code":
            if lang == "python" or lang == "python2":
                c = HTMLBashCodeToPythonNotebookConverter(
                    notebook,
                    grass=args.grass,
                    gisdbase=args.gisdbase,
                    location=args.location,
                    mapset=args.mapset,
                    python2=lang == "python2",
                )
            if lang in ("bash", "bash-cells", "pure-bash"):
                if lang == "bash":
                    syntax = "!"
                elif lang == "bash-cells":
                    syntax = "cell"
                elif lang == "pure-bash":
                    syntax = "pure"
                c = HTMLBashCodeToNotebookConverter(
                    notebook,
                    syntax=syntax,
                    grass=args.grass,
                    gisdbase=args.gisdbase,
                    location=args.location,
                    mapset=args.mapset,
                )
            c.feed("\n".join(block["content"]))
            c.finish()
        elif block["block_type"] == "file_content":
            c = HTMLFileContentToPythonNotebookConverter(
                notebook, filename=block["attrs"]["filename"]
            )
            c.feed("\n".join(block["content"]))
            c.finish()
        elif block["block_type"] == "text":
            c = HTMLToMarkdownNotebookConverter(notebook)
            c.feed("\n".join(block["content"]))
            c.finish()
            filenames.extend(c.download_files)
            if first_text_cell and args.session_after_text:
                add_session_start = True
            first_text_cell = False

    if filenames:
        add_file_downloads(notebook, filenames, lang == "python2")
    finish_session(notebook)

    with open(output, "w") as f:
        nbf.write(notebook, f)


def test():
    import doctest

    doctest.testmod()


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--doctest":
        sys.exit(test())
    main()
