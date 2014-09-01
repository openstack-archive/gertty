Contributing
============

To browse the latest code, see: https://git.openstack.org/cgit/stackforge/gertty/tree/
To clone the latest code, use `git clone git://git.openstack.org/stackforge/gertty`

Bugs are handled at: https://storyboard.openstack.org/

Code reviews are handled by gerrit at: https://review.openstack.org

Use `git review` to submit patches (after creating a gerrit account
that links to your launchpad account). Example::

    # Do your commits
    $ git review
    # Enter your username if prompted

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

* Support a wide variety of Gerrit installations.  The initial
  development of Gertty is against the OpenStack project's Gerrit, and
  many of the features are intended to help its developers with their
  workflow, however, those features should be implemented in a generic
  way so that the system does not require a specific Gerrit
  configuration.

