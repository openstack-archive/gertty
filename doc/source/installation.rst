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
