"""Ausschließlich erfundene Boninhalte; echte Daten nie als Fixtures."""
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

TEXT = '''Kaufland - Testfiliale
Preis EUR
Testmilch 2 * 1,50 3,00 B
Testapfel
0,500 kg 1,00 B
K Card XTRA Rabatt -0,20
Summe 3,80
B 7,00% 3,80 3,55 0,25
Datum 30.10.26 17:53 Uhr
'''


def pdf(path, text=TEXT, metadata=None):
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=800)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica'), NameObject('/Encoding'): NameObject('/WinAnsiEncoding')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    operations = ['BT /F1 9 Tf 12 TL 10 780 Td']
    for line in text.splitlines():
        safe = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        operations.append('(' + safe + ') Tj T*')
    operations.append('ET')
    stream.set_data('\n'.join(operations).encode('cp1252'))
    page[NameObject('/Contents')] = writer._add_object(stream)
    if metadata:
        writer.add_metadata(metadata)
    writer.write(path)
    return path
