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

Usage
-----

Create a file at ``~/.gertty.yaml`` with the following contents::

  servers:
    - name: gerrit
      url: https://review.example.org/
      username: <gerrit username>
      password: <gerrit password>
      git_root: ~/git/

You can generate or retrieve your Gerrit password by navigating to
Settings, then HTTP Password.  Set ``git_root`` to a directory where
Gertty should find or clone git repositories for your projects.

If your Gerrit uses a self-signed certificate, you can add::

  verify_ssl: False

To the section.

The config file is designed to support multiple Gerrit instances, but
currently, only the first one is used.

After installing the requirements (listed in requirements.txt), you
should be able to simply run Gertty.  You will need to start by
subscribing to some projects.  Use 'l' to list all of the projects and
then 's' to subscribe to them.

In general, pressing the F1 key will show help text on any screen, and
ESC will take you to the previous screen.

To select text (e.g., to copy to the clipboard), hold Shift while
selecting the text.

Philosophy
----------

Gertty is based on the following precepts which should inform changes
to the program:

* Support large numbers of review requests across large numbers of
  projects.  Help the user prioritize those reviews.

* Adopt a news/mailreader-like workflow in support of the above.
  Being able to subscribe to projects, mark reviews as "read" without
  reviewing, etc, are all useful concepts to support a heavy review
  load (they have worked extremely well in supporting people who
  read/write a lot of mail/news).

* Support off-line use.  Gertty should be completely usable off-line
  with reliable syncing between local data and Gerrit when a
  connection is available (just like git or mail or news).

* Ample use of color.  Unlike a web interface, a good text interface
  relies mostly on color and precise placement rather than whitespace
  and decoration to indicate to the user the purpose of a given piece
  of information.  Gertty should degrade well to 16 colors, but more
  (88 or 256) may be used.

* Keyboard navigation (with easy-to-remember commands) should be
  considered the primary mode of interaction.  Mouse interaction
  should also be supported.

* The navigation philosophy is a stack of screens, where each
  selection pushes a new screen onto the stack, and ESC pops the
  screen off.  This makes sense when drilling down to a change from
  lists, but also supports linking from change to change (via commit
  messages or comments) and navigating back intuitive (it matches
  expectations set by the web browsers).
