# gdoc2py

_gdoc2py_ is a GRASS GIS focused converter from HTML to Jupyter Notebook.
It is based on recognizing `<pre>` and `<code>` tags and splitting
the document into notebook cells.

For GRASS GIS modules it converts command line syntax (simple command
line, not full Bash) to Python syntax or just adds `!` before the
commands. It does some additions for first parameter and display modules
if needed. It also adds session initialization and clean up code.

For text it converts (some of) HTML tags to Markdown and ignores rest
of it.

## Possible future work

* refactoring of "lines of code to output language" code
* output for Jupyter Notebooks with Bash kernel (some code already there)
* output for Jupyter Notebooks with R kernel
* reading GRASS GIS manual pages (requires some clean up there) for documentation testing purposes
 * https://lists.osgeo.org/pipermail/grass-dev/2014-December/072606.html
* writing pure Bash (or Python, but not a notebook) for documentation testing purposes
 * https://github.com/ncsu-geoforall-lab/geospatial-modeling-course/blob/master/doc2tests.py
* reading some simplified non-JSON (likely Markdown) representation of Jupyer Notebooks
* download links marked with the `download` attribute

## Author

Vaclav Petras

## License

This program is free software under the GNU General Public License
(>=v2). Read the file LICENSE for details.
