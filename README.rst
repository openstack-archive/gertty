Gertty
======

Gertty is a console-based interface to the Gerrit Code Review system.

As compared to the web interface, the main advantages are:

 * Workflow -- the interface is designed to support a workflow similar
   to reading network news or mail.  In particular, it is designed to
   deal with a large number of review requests across a large number
   of projects.

 * Offline Use -- Gertty syncs information about changes in subscribed
   projects to a local database and local git repos.  All review
   operations are performed against that database and then synced back
   to Gerrit.

 * Speed -- user actions modify locally cached content and need not
   wait for server interaction.

 * Convenience -- because Gertty downloads all changes to local git
   repos, a single command instructs it to checkout a change into that
   repo for detailed examination or testing of larger changes.

Installation
------------

Debian
~~~~~~

Gertty is packaged in Debian and is currently available in:

 * unstable
 * testing
 * stable

You can install it with::

  apt-get install gertty

Fedora
~~~~~~

Gertty is packaged starting in Fedora 21.  You can install it with::

  yum install python-gertty

openSUSE
~~~~~~~~

Gertty is packaged for openSUSE 13.1 onwards.  You can install it via
`1-click install from the Open Build Service <http://software.opensuse.org/package/python-gertty>`_.

Arch Linux
~~~~~~~~~~

Gertty packages are available in the Arch User Repository packages. You
can get the package from::

  https://aur.archlinux.org/packages/python2-gertty/

Source
~~~~~~

When installing from source, it is recommended (but not required) to
install Gertty in a virtualenv.  To set one up::

  virtualenv gertty-env
  source gertty-env/bin/activate

To install the latest version from the cheeseshop::

  pip install gertty

To install from a git checkout::

  pip install .

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

Usage
-----

After installing Gertty, you should be able to run it by invoking
``gertty``.  If you installed it in a virtualenv, you can invoke it
without activating the virtualenv with ``/path/to/venv/bin/gertty``
which you may wish to add to your shell aliases.  Use ``gertty
--help`` to see a list of command line options available.

Once Gertty is running, you will need to start by subscribing to some
projects.  Use 'L' to list all of the projects and then 's' to
subscribe to the ones you are interested in.  Hit 'L' again to shrink
the list to your subscribed projects.

In general, pressing the F1 key will show help text on any screen, and
ESC will take you to the previous screen.

Gertty works seamlessly offline or online.  All of the actions that it
performs are first recorded in a local database (in ``~/.gertty.db``
by default), and are then transmitted to Gerrit.  If Gertty is unable
to contact Gerrit for any reason, it will continue to operate against
the local database, and once it re-establishes contact, it will
process any pending changes.

The status bar at the top of the screen displays the current number of
outstanding tasks that Gertty must perform in order to be fully up to
date.  Some of these tasks are more complicated than others, and some
of them will end up creating new tasks (for instance, one task may be
to search for new changes in a project which will then produce 5 new
tasks if there are 5 new changes).

If Gertty is offline, it will so indicate in the status bar.  It will
retry requests if needed, and will switch between offline and online
mode automatically.

If you review a change while offline with a positive vote, and someone
else leaves a negative vote on that change in the same category before
Gertty is able to upload your review, Gertty will detect the situation
and mark the change as "held" so that you may re-inspect the change
and any new comments before uploading the review.  The status bar will
alert you to any held changes and direct you to a list of them (the
`F12` key by default).  When viewing a change, the "held" flag may be
toggled with the exclamation key (`!`).  Once held, a change must be
explicitly un-held in this manner for your review to be uploaded.

If Gertty encounters an error, this will also be indicated in the
status bar.  You may wish to examine ~/.gertty.log to see what the
error was.  In many cases, Gertty can continue after encountering an
error.  The error flag will be cleared when you leave the current
screen.

To select text (e.g., to copy to the clipboard), hold Shift while
selecting the text.

Terminal Integration
--------------------

If you use rxvt-unicode, you can add something like the following to
``.Xresources`` to make Gerrit URLs that are displayed in your
terminal (perhaps in an email or irc client) clickable links that open
in Gertty::

  URxvt.perl-ext:           default,matcher
  URxvt.url-launcher:       sensible-browser
  URxvt.keysym.C-Delete:    perl:matcher:last
  URxvt.keysym.M-Delete:    perl:matcher:list
  URxvt.matcher.button:     1
  URxvt.matcher.pattern.1:  https:\/\/review.example.org/(\\#\/c\/)?(\\d+)[\w]*
  URxvt.matcher.launcher.1: gertty --open $0

You will want to adjust the pattern to match the review site you are
interested in; multiple patterns may be added as needed.

Contributing
------------

For information on how to contribute to Gertty, please see the
contents of the CONTRIBUTING.rst file.

Bugs
----

Bugs are handled at: https://storyboard.openstack.org/#!/project/698
