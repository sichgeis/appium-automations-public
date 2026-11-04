"""Händler ausschließlich anhand beobachteter Oberflächen anbinden."""


def adapter_for(merchant, driver):
    from ..retailers import require_export_implementation
    require_export_implementation(merchant)
    if merchant == 'kaufland':
        from .kaufland import Kaufland
        return Kaufland(driver)
    if merchant == 'rossmann':
        from .rossmann import Rossmann
        return Rossmann(driver)
    if merchant == 'dm':
        from .dm import Dm
        return Dm(driver)
    if merchant == 'lidl':
        from .lidl import Lidl
        return Lidl(driver)
    raise ValueError('Kein implementierter Händleradapter registriert.')
