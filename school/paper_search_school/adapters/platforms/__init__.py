"""Website platforms: the shared rules of one website system that several
publishers run on (Atypon, Silverchair). A platform is not a publisher: each
publisher keeps its own folder in ``adapters/`` and inherits its platform's
adapter there, adding only what is its own (docs/adr/0014). A platform whose
publishers have no profile (J-STAGE's societies) registers its adapter for the
profile the engine builds for the site at run time (``site:<domain>``), on its
own hosts only.
"""
