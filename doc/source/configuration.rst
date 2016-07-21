Configuration
-------------

Gertty uses a YAML based configuration file that it looks for at
``~/.gertty.yaml``.  Several sample configuration files are included.
You can find them in the examples/ directory of the
`source distribution <https://git.openstack.org/cgit/openstack/gertty/tree/examples>`_
or the share/gertty/examples directory after installation.

Select one of the sample config files, copy it to ~/.gertty.yaml and
edit as necessary.  Search for ``CHANGEME`` to find parameters that
need to be supplied.  The sample config files are as follows:

**minimal-gertty.yaml**
  Only contains the parameters required for Gertty to actually run.

**reference-gertty.yaml**
  An exhaustive list of all supported options with examples.

**openstack-gertty.yaml**
  A configuration designed for use with OpenStack's installation of
  Gerrit.

**googlesource-gertty.yaml**
  A configuration designed for use with installations of Gerrit
  running on googlesource.com.

You will need your Gerrit password which you can generate or retrieve
by navigating to ``Settings``, then ``HTTP Password``.

Gertty uses local git repositories to perform much of its work.  These
can be the same git repositories that you use when developing a
project.  Gertty will not alter the working directory or index unless
you request it to (and even then, the usual git safeguards against
accidentally losing work remain in place).  You will need to supply
the name of a directory where Gertty will find or clone git
repositories for your projects as the ``git-root`` parameter.

The config file is designed to support multiple Gerrit instances.  The
first one is used by default, but others can be specified by supplying
the name on the command line.

Configuration Reference
~~~~~~~~~~~~~~~~~~~~~~~

The following describes the values that may be set in the
configuration file.

Servers
+++++++

This section lists the servers that Gertty can talk to.  Multiple
servers may be listed; by default, Gertty will use the first one
listed.  To select another, simply specify its name on the command
line.

**servers**
  A list of server definitions.  The format of each entry is described
  below.

  **name (required)**
    A name that describes the server, to reference on the command
    line.

  **url (required)**
    The URL of the Gerrit server.  HTTPS should be preferred.

  **username (required)**
    Your username in Gerrit. [required]

  **password (required)**
    Your password in Gerrit.  Obtain it from Settings -> HTTP Password
    in the Gerrit web interface.

  **auth-type**
    Authentication type required by the Gerrit server. Can be 'basic',
    'digest', or 'form'. Defaults to 'digest'.

  **git-root (required)**
    A location where Gertty should store its git repositories.  These
    can be the same git repositories where you do your own work --
    Gertty will not modify them unless you tell it to, and even then
    the normal git protections against losing work remain in place.

  **dburi**
    The location of Gertty's sqlite database.  If you have more than
    one server, you should specify a dburi for any additional servers.
    By default a SQLite database called ~/.gertty.db is used.

  **ssl-ca-path**
    If your Gerrit server uses a non-standard certificate chain
    (e.g. on a test server), you can pass a full path to a bundle of
    CA certificates here:

  **verify-ssl**
    In case you do not care about security and want to use a
    sledgehammer approach to SSL, you can set this value to false to
    turn off certificate validation.

  **log-file**
    By default Gertty logs errors to a file and truncates that file
    each time it starts (so that it does not grow without bound).  If
    you would like to log to a different location, you may specify it
    with this option.

  **socket**
    Gertty listens on a unix domain socket for remote commands at
    ~/.gertty.sock.  This option may be used to change the path.

  **lock-file**
    Gertty uses a lock file per server to prevent multiple processes
    from running at the same time. The default is ~/.gertty.servername.lock

Example:

.. code-block: yaml
   servers:
     - name: CHANGEME
       url: https://CHANGEME.example.org/
       username: CHANGEME
       password: CHANGEME
       git-root: ~/git/

Palettes
++++++++

Gertty comes with two palettes defined internally.  The default
palette is suitable for use on a terminal with a dark background.  The
`light` palette is for a terminal with a white or light background.
You may customize the colors in either of those palettes, or define
your own palette.

If any color is not defined in a palette, the value from the default
palette is used.  The values are a list of at least two elements
describing the colors to be used for the foreground and background.
Additional elements may specify (in order) the color to use for
monochrome terminals, the foreground, and background colors to use in
high-color terminals.

For a reference of possible color names, see the `Urwid Manual
<http://urwid.org/manual/displayattributes.html#foreground-and-background-settings>`_

To see the list of possible palette entries, run `gertty --print-palette`.

The following example alters two colors in the default palette, one
color in the light palette, and one color in a custom palette.

.. code-block: yaml
   palettes:
     - name: default
       added-line: ['dark green', '']
       added-word: ['light green', '']
     - name: light
       filename: ['dark cyan', '']
     - name: custom
       filename: ['light yellow', '']

Palettes may be selected at runtime with the `-p PALETTE` command
line option, or you may set the default palette in the config file.

**palette**
  This option specifies the default palette.

Keymaps
+++++++

Keymaps work the same way as palettes.  Two keymaps are defined
internally, the `default` keymap and the `vi` keymap.  Individual keys
may be overridden and custom keymaps defined and selected in the
config file or the command line.

Each keymap contains a mapping of command -> key(s).  If a command is
not specified, Gertty will use the keybinding specified in the default
map.  More than one key can be bound to a command.

Run `gertty --print-keymap` for a list of commands that can be bound.

The following example modifies the `default` keymap:

.. code-block: yaml
   keymaps:
     - name: default
       diff: 'd'
     - name: custom
       review: ['r', 'R']
     - name: osx #OS X blocks ctrl+o
       change-search: 'ctrl s'


To specify a sequence of keys, they must be a list of keystrokes
within a list of key series.  For example:

.. code-block: yaml
   keymaps:
     - name: vi
       quit: [[':', 'q']]

The default keymap may be selected with the `-k KEYMAP` command line
option, or in the config file.

**keymap**
  Set the default keymap.

Commentlinks
++++++++++++

Commentlinks are regular expressions that are applied to commit and
review messages.  They can be replaced with internal or external
links, or have colors applied.

**commentlinks**
  This is a list of commentlink patterns.  Each commentlink pattern is
  a dictionary with the following values:

  **match**
    A regular expression to match against the text of commit or review
    messages.

  **replacements**
    A list of replacement actions to apply to any matches found.
    Several replacement actions are supported, and each accepts
    certain options.  These options may include strings extracted from
    the regular expression match in named groups by enclosing the
    group name in '{}' braces.

  The following replacement actions are supported:

    **text**
      Plain text whose color may be specified.

      **text**
        The replacement text.

      **color**
        The color in which to display the text.  This references a
        palette entry.

    **link**
      A hyperlink with the indicated text that when activated will
      open the user's browser with the supplied URL

      **text**
        The replacement text.

      **url**
        The color in which to display the text.  This references a
        palette entry.

    **search**
      A hyperlink that will perform a Gertty search when activated.

      **text**
        The replacement text.

      **query**
        The search query to use.

This example matches Gerrit change ids, and replaces them with a link
to an internal Gertty search for that change id.

.. code-block: yaml
   commentlinks:
     - match: "(?P<id>I[0-9a-fA-F]{40})"
       replacements:
         - search:
             text: "{id}"
             query: "change:{id}"

Change List Options
+++++++++++++++++++

**change-list-query**
  This is the query used for the list of changes when a project is
  selected.  The default is `status:open`.

**change-list-options**
  This section defines default sorting options for the change list.

  **sort-by**
    This key specifies the sort order, which can be `number` (the
    Change number), `updated` (when the change was last updated), or
    `last-seen` (when the change was last opened in Gertty).

  **reverse**
    This is a boolean value which indicates whether the list should be
    in ascending (`true`) or descending (`false`) order.

Example:

.. code-block: yaml
   change-list-options:
     sort-by: 'number'
     reverse: false

**thread-changes**
  Dependent changes are displayed as "threads" in the change list by
  default.  To disable this behavior, set this value to false.

Change View Options
+++++++++++++++++++

**hide-comments**
  This is a list of descriptors which cause matching comments to be
  hidden by default.  Press the `t` key to toggle the display of
  matching comments.

The only supported criterion is `author`.

  **author**
    A regular expression to match against the comment author's name.

For example, to hide comments from a CI system:

.. code-block: yaml

   hide-comments:
     - author: "^(.*CI|Jenkins)$"

**diff-view**
  Specifies how patch diffs should be displayed.  The values `unified`
  or `side-by-side` (the default) are supported.


Dashboards
++++++++++

This section defines customized dashboards.  You may supply any
Gertty search string and bind them to any key.  They will appear in
the global help text, and pressing the key anywhere in Gertty will
run the query and display the results.

**dashboards**
  A list of dashboards, the format of which is described below.

  **name**
    The name of the dashboard.  This will be displayed in the status
    bar at the top of the screen.

  **query**
    The search query to perform to gather changes to be listed in the
    dashboard.

  **key**
    The key to which the dashboard should be bound.

Example:

.. code-block: yaml

   dashboards:
     - name: "My changes"
       query: "owner:self status:open"
       key: "f2"

Reviewkeys
++++++++++

Reviewkeys are hotkeys that perform immediate reviews within the
change screen.  Any pending comments or review messages will be
attached to the review; otherwise an empty review message will be
left.  The approvals list is exhaustive, so if you specify an empty
list, Gertty will submit a review that clears any previous approvals.
Reviewkeys appear in the help text for the change screen.

**reviewkeys**
  A list of reviewkey definitions, the format of which is described
  below.

  **key**
    This key to which this review action should be bound.

  **approvals**
    A list of approvals to include when this reviewkey is activated.
    Each element of the list should include both a category and a
    value.

    **category**
      The name of the review label for this approval.

    **value**
      The value for this approval.

  **submit**
    Set this to `true` to instruct Gerrit to submit the change when
    this reviewkey is activated.

The following example includes a reviewkey that clears all labels, as
well as one that leaves a +1 "Code-Review" approval.

.. code-block: yaml

   reviewkeys:
     - key: 'meta 0'
       approvals: []
     - key: 'meta 1'
       approvals:
         - category: 'Code-Review'
           value: 1

General Options
+++++++++++++++

**breadcrumbs**
  Gertty displays a footer at the bottom of the screen by default
  which contains navigation information in the form of "breadcrumbs"
  -- short descriptions of previous screens, with the right-most entry
  indicating the screen that will be displayed if you press the `ESC`
  key.  To disable this feature, set this value to `false`.

**display-times-in-utc**
  Times are displayed in the local timezone by default.  To display
  them in UTC instead, set this value to `true`.

**handle-mouse**
  Gertty handles mouse input by default.  If you don't want it
  interfering with your terminal's mouse handling, set this value to
  `false`.

**expire-age**
  By default, closed changes that are older than two months are
  removed from the local database (and their refs are removed from the
  local git repos so that git may garbage collect them).  If you would
  like to change the expiration delay or disable it, uncomment the
  following line.  The time interval is specified in the same way as
  the "age:" term in Gerrit's search syntax.  To disable it
  altogether, set the value to the empty string.
