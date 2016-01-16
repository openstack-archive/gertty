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
