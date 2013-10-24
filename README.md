BuildSlave
==========

A build-slave forms part of the SolusOS packaging infrastructure and a core part of the
build-services.

Concepts
--------
The slave will connect to the repohub frontend, asking for a queue to build. After authorization, etc,
the slave will download the latest revision of the repository in question, and build the queue that it
has been given.

The slave will only build .pisi packages and is not responsible for indexing or organising a repository,
nor will it produce delta packages. In the SolusOS design, this is handled by *binman*. It is slave's job
to upload the binary packages to the incoming directory of its target repository, where binman takes over.

Authors
-------
* Ikey Doherty <ikey@solusos.com>


