import gzip
import struct
import tempfile
import unittest
from pathlib import Path
from test_x86_build import load_build


def efi_image(path, root_sectors=1966080):
    data = bytearray(34 * 512)
    data[510:512] = b'\x55\xaa'
    data[512:520] = b'EFI PART'
    struct.pack_into('<Q', data, 512 + 72, 2)
    struct.pack_into('<II', data, 512 + 80, 128, 128)
    for index, start, sectors in [(0, 512, 131072), (1, 131584, root_sectors)]:
        offset = 1024 + index * 128
        data[offset:offset+16] = b'1' * 16
        struct.pack_into('<QQ', data, offset+32, start, start+sectors-1)
    with gzip.open(path, 'wb') as archive:
        archive.write(data)


class ReleaseTests(unittest.TestCase):
    def test_wrong_partition_size_and_non_efi_image_rejected(self):
        build = load_build()
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'firmware.img.gz'
            efi_image(image)
            self.assertEqual(build.image_partitions(image), [[1, 512, 131072], [2, 131584, 1966080]])
            efi_image(image, root_sectors=3145728)
            with self.assertRaisesRegex(ValueError, '960'):
                build.image_partitions(image)
            with gzip.open(image, 'wb') as archive:
                archive.write(b'not EFI')
            with self.assertRaisesRegex(ValueError, 'EFI'):
                build.image_partitions(image)

    def test_missing_manifest_plugin_blocks_release(self):
        build = load_build()
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'image.manifest'
            manifest.write_text('kmod-igc - 6.18.62-r1\n')
            with self.assertRaisesRegex(ValueError, 'luci-app-openclash'):
                build.check_manifest(manifest, {'CONFIG_PACKAGE_luci-app-openclash': 'y'})
            manifest.write_text('kmod-igc - 6.18.62-r1\nluci-app-openclash - 0.48.002\n')
            versions = build.check_manifest(manifest, {'CONFIG_PACKAGE_luci-app-openclash': 'y'})
            self.assertEqual(versions['luci-app-openclash'], '0.48.002')

    def test_stale_checksum_is_replaced_by_actual_asset_hash(self):
        build = load_build()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output/'image.img.gz').write_bytes(b'firmware')
            (output/'sha256sums').write_text('wrong image.img.gz\n')
            build.write_checksums(output)
            self.assertEqual((output/'sha256sums').read_text(),
                'c3bf47ea1f4a4a605470313cacb3a44f4a461f68c6faeab07e737610cb5ac835  image.img.gz\n')


if __name__ == '__main__':
    unittest.main()
