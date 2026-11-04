from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib
from receiptbot.workflow import Exports
from receiptbot.reporting import report
from receiptbot.archive import file_digest
from test_lidl import TEXT


def synthetic_png(path, note):
    # Echte 1x1-PNG-Struktur; OCR-/Beleginhalt wird für diese Logiktests ersetzt.
    def chunk(tag,data):
        return struct.pack('!I',len(data)) + tag + data + struct.pack('!I',zlib.crc32(tag+data)&0xffffffff)
    raw = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR',struct.pack('!2I5B',1,1,8,6,0,0,0))
    raw += chunk(b'tEXt',b'synthetic\0'+note.encode())
    raw += chunk(b'IDAT',zlib.compress(b'\0\xff\xff\xff\xff')) + chunk(b'IEND',b'')
    path.write_bytes(raw)
    return path


class ImageArchiveTests(unittest.TestCase):
    def test_image_is_never_archived_as_pdf_and_variants_keep_original_bytes(self):
        expected = dict(merchant='lidl',date='2026-02-01',total_cents=330,text=TEXT)
        image = dict(complete=True,format='public.png',width=1,height=1,text=TEXT,observations=[],
                     pixel_layout=[8,32,4],pixel_sha256='a'*64)
        with tempfile.TemporaryDirectory() as directory, patch('receiptbot.images.read_image',return_value=image):
            root=Path(directory);store=Exports(root/'data',root/'output')
            # Falsche Quell-Endung darf niemals zur falschen Original-Endung führen.
            a=synthetic_png(root/'synthetic-wrong-extension.pdf','A')
            first=store.adopt_received(expected,a)
            self.assertEqual(first['path'].suffix,'.png')
            b=synthetic_png(root/'synthetic-B.png','B')
            self.assertNotEqual(file_digest(a),file_digest(b))
            second=store.adopt_received(expected,b)
            self.assertTrue(second['duplicate_by_receipt_id'])
            self.assertEqual(first['path'],second['path'])
            self.assertEqual(first['path'].read_bytes(),a.read_bytes())
            self.assertEqual(store.verified_count('lidl'),1)
            self.assertEqual(len(list((root/'output/inbox').glob('*.png'))),2)
            self.assertEqual(report(root/'data',root/'output'),(1,3))
            csv=(root/'output/reports/receipts.csv').read_text()
            self.assertIn('png,app_accessibility',csv)
