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


Contents:

.. toctree::
   :maxdepth: 1

   installation.rst
   configuration.rst
   usage.rst
   contributing.rst

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

