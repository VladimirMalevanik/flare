"""Synthetic bounded ZIP security/fidelity fixtures. No customer or provider data."""
from dataclasses import replace
import io
import json
import stat
import struct
import zipfile
import pytest
from app.import_staging import LocalStagedObjects
from app.import_staging.policy import ImportPolicy
from app.services.zip_import import ZipRejected, manifest, parse_entry, verified_bytes


def archive_bytes(entries, *, compression=zipfile.ZIP_DEFLATED):
    result=io.BytesIO()
    with zipfile.ZipFile(result,'w',compression=compression) as z:
        for name,value in entries:
            z.writestr(name,value)
    return result.getvalue()


def inspect(raw, policy=None):
    policy=policy or ImportPolicy()
    stream=io.BytesIO(raw)
    rows=manifest(stream,policy)
    results=[]
    with zipfile.ZipFile(stream) as z:
        for row,info in zip(rows,z.infolist()):
            content,digest=verified_bytes(stream,z,info,policy,policy.expanded_bytes)
            results.append((row,digest,parse_entry(content,row,policy)))
    return results


def test_notions_and_obsidian_fidelity_unicode_duplicate_titles_multiline_csv():
    notes='---\ntags: [research]\n---\n# Café\nUnicode Привет 👋\n<script>never executed</script>\n'
    csv='name,signal\n"Café","line one\nline two, quoted"\n'
    result=inspect(archive_bytes([('notes/Idea.md',notes),('other/Idea.markdown',notes),('España/数据.csv',csv),('readme.txt','hello\n')]))
    assert len(result)==4
    for row,_,parsed in result:
        assert parsed['status']=='prepared'
        expected=csv if row['path'].endswith('.csv') else 'hello\n' if row['path'].endswith('.txt') else notes
        assert ''.join(c['content'] for c in parsed['chunks'])==expected
        assert all(c['locator']['relativePath']==row['path'] for c in parsed['chunks'])


@pytest.mark.parametrize('path',['../evil.md','/absolute.md','C:/drive.md','\\\\server\\share.md','a\\..\\evil.md','a/../b.md','a//b.md','a/./b.md','x\x00.md','x\n.md','a:b.md'])
def test_unsafe_paths(path):
    with pytest.raises((ZipRejected,zipfile.BadZipFile)):
        raw=archive_bytes([(path.replace('\x00','?'),'hello')])
        inspect(raw.replace(b'?',b'\x00') if '\x00' in path else raw)


@pytest.mark.parametrize('paths',[['A.md','a.md'],['café.md','cafe\u0301.md'],['a.md','a.md'],['folder','folder/x.md']])
def test_canonical_collisions(paths):
    with pytest.raises(ZipRejected,match='path_collision'):
        inspect(archive_bytes([(p,'hi') for p in paths]))


@pytest.mark.parametrize('mode',[stat.S_IFLNK,stat.S_IFIFO,stat.S_IFCHR,stat.S_IFSOCK])
def test_special_objects(mode):
    info=zipfile.ZipInfo('unsafe.md'); info.create_system=3; info.external_attr=(mode|0o600)<<16
    with pytest.raises(ZipRejected,match='special_entry'):
        inspect(archive_bytes([(info,'target')]))


def test_every_unsupported_asset_is_skipped_not_parsed():
    paths=['photo.png','paper.pdf','sound.mp3','movie.mp4','word.docx','nested.zip','page.html','state.json','drawing.canvas','.obsidian/plugins/script.js','.obsidian/notes.md','.git/config','folder/']
    result=inspect(archive_bytes([(p,b'\x00binary' if not p.endswith('/') else b'') for p in paths]))
    assert all(parsed['status']=='skipped' for _,_,parsed in result)
    assert result[10][2]['reason']=='application_configuration'


@pytest.mark.parametrize('policy,entries,code',[
    (replace(ImportPolicy(),entries=1),[('a.md','a'),('b.md','b')],'manifest_bound'),
    (replace(ImportPolicy(),directory_bytes=1),[('a.md','a')],'manifest_bound'),
    (replace(ImportPolicy(),manifest_bytes=1),[('a.md','a')],'manifest_bound'),
    (replace(ImportPolicy(),file_bytes=10,chunk_bytes=5),[('a.md','x'*11)],'file_bytes'),
    (replace(ImportPolicy(),expanded_bytes=10),[('a.md','x'*6),('b.md','y'*6)],'expanded_bytes'),
    (replace(ImportPolicy(),compressed_bytes=20),[('a.md','a')],'compressed_bytes'),
    (replace(ImportPolicy(),expansion_ratio=2),[('a.md','x'*10000)],'expansion_ratio'),
    (replace(ImportPolicy(),path_bytes=5),[('long-name.md','a')],'path_bound'),
    (replace(ImportPolicy(),path_depth=2),[('a/b/c.md','a')],'path_bound'),
    (replace(ImportPolicy(),segment_bytes=5),[('long-name.md','a')],'path_bound'),
    (replace(ImportPolicy(),csv_rows=1),[('a.csv','name\na\nb\n')],'too_many_rows'),
    (replace(ImportPolicy(),csv_field_bytes=3),[('a.csv','name\nabcde\n')],'csv_field_bound'),
    (replace(ImportPolicy(),csv_row_bytes=5),[('a.csv','a,b\n123,456\n')],'csv_row_bound'),
    (replace(ImportPolicy(),chunks_file=1,chunk_bytes=10),[('a.txt','hello\n'*20)],'too_many_chunks'),
])
def test_independent_bounds(policy,entries,code):
    with pytest.raises(ZipRejected,match=code): inspect(archive_bytes(entries),policy)


def patch_headers(raw,offset,value,central_offset=None):
    data=bytearray(raw)
    struct.pack_into('<H',data,offset,value)
    if central_offset is not None: struct.pack_into('<H',data,data.index(b'PK\x01\x02')+central_offset,value)
    return bytes(data)


def test_encryption_and_unsupported_compression():
    raw=archive_bytes([('note.md','hello')])
    with pytest.raises(ZipRejected,match='encrypted_zip'): inspect(patch_headers(raw,6,1,8))
    with pytest.raises(ZipRejected,match='compression_method'): inspect(patch_headers(raw,8,99,10))


@pytest.mark.parametrize('raw',[b'',b'hello',b'PK\x03\x04',archive_bytes([('note.md','hello')])[:-5]])
def test_malformed_or_truncated(raw):
    with pytest.raises((ZipRejected,zipfile.BadZipFile)): inspect(raw)


@pytest.mark.parametrize('path',['note.md','asset.png'])
def test_crc_corruption_even_skipped_asset(path):
    raw=bytearray(archive_bytes([(path,'hello')],compression=zipfile.ZIP_STORED))
    raw[30+len(path)]^=1
    with pytest.raises(ZipRejected,match='integrity_failure'): inspect(bytes(raw))


def test_dishonest_size_cannot_silently_truncate_decompression():
    raw=bytearray(archive_bytes([('note.md','hello'*1000)]))
    struct.pack_into('<L',raw,22,1)
    struct.pack_into('<L',raw,raw.index(b'PK\x01\x02')+24,1)
    with pytest.raises(ZipRejected,match='integrity_failure'): inspect(bytes(raw))


@pytest.mark.parametrize('content',[b'\xff',b'\x00binary',b'','   '])
def test_supported_invalid_text_is_package_failure(content):
    with pytest.raises(ZipRejected): inspect(archive_bytes([('note.md',content)]))


def test_local_objects_private_immutable_no_symlinks(tmp_path):
    storage=LocalStagedObjects(tmp_path/'private')
    key='a'*32+'-'+'b'*32
    with storage.writer(key) as out: out.write(b'zip')
    assert storage.size(key)==3
    assert (storage.root/(key+'.zip')).stat().st_mode&0o777==0o600
    with pytest.raises(FileExistsError):
        with storage.writer(key) as out: out.write(b'replacement')
    with storage.reader(key) as original: assert original.read()==b'zip'
    storage.delete(key); storage.delete(key)
    (storage.root/(key+'.zip')).symlink_to(tmp_path/'other')
    with pytest.raises(OSError):
        with storage.reader(key): pass
    storage.delete(key)
    with pytest.raises(ValueError): storage.delete('../unsafe')


def test_policy_configuration_has_no_production_defaults(monkeypatch):
    with pytest.raises(ValueError,match='explicit'): ImportPolicy.from_environment(production=True)
    monkeypatch.setenv('FLARE_IMPORT_FILE_BYTES','120000')
    assert ImportPolicy.from_environment().file_bytes==120000
    with pytest.raises(ValueError): replace(ImportPolicy(),lease_seconds=0)


def test_leading_markdown_whitespace_and_bom_preserve_supported_text():
    text='\n\n# Heading\nText\n'
    result=inspect(archive_bytes([('note.md',b'\xef\xbb\xbf'+text.encode())]))
    assert ''.join(c['content'] for c in result[0][2]['chunks'])==text
    assert all(c['content'].strip() for c in result[0][2]['chunks'])


@pytest.mark.parametrize('path',['CON.md','a.md ','folder//','a\u202eb.md','a?.md'])
def test_portable_reserved_names_and_format_controls(path):
    with pytest.raises(ZipRejected,match='unsafe_path'):
        inspect(archive_bytes([(path,'hello')]))


def test_dishonest_eocd_count_is_bounded_before_zipfile_allocation(monkeypatch):
    raw=bytearray(archive_bytes([('a.md','hello'),('b.md','world')]))
    end=raw.rfind(b'PK\x05\x06')
    struct.pack_into('<2H',raw,end+8,1,1)
    monkeypatch.setattr(zipfile,'ZipFile',lambda *a,**kw: pytest.fail('Directory allocated before actual entry validation'))
    with pytest.raises(ZipRejected,match='manifest_bound'):
        manifest(io.BytesIO(raw),replace(ImportPolicy(),entries=1))


def test_cleanup_tombstone_fences_a_writer_paused_before_object_creation(tmp_path):
    storage=LocalStagedObjects(tmp_path/'private')
    key='c'*32+'-'+'d'*32
    storage.delete(key)
    with pytest.raises(FileExistsError,match='retired'):
        with storage.writer(key) as stream:stream.write(b'late payload')
    assert not list(storage.root.glob('*.zip')) and not list(storage.root.glob('*.part'))


def test_cleanup_cannot_unlink_an_active_writer_and_is_retryable(tmp_path):
    storage=LocalStagedObjects(tmp_path/'private')
    key='e'*32+'-'+'f'*32
    with storage.writer(key) as stream:
        stream.write(b'payload')
        with pytest.raises(BlockingIOError):storage.delete(key)
    storage.delete(key)
    with pytest.raises(FileExistsError):
        with storage.writer(key):pass


def test_streaming_zip_data_descriptor_integrity():
    class Unseekable(io.BytesIO):
        def seek(self,*a):raise OSError('stream')
    stream=Unseekable()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:archive.writestr('note.md','valid streamed archive')
    raw=stream.getvalue()
    assert inspect(raw)[0][2]['status']=='prepared'
    corrupt=bytearray(raw);offset=corrupt.index(b'PK\x07\x08');corrupt[offset+4]^=1
    with pytest.raises(ZipRejected,match='integrity_failure'):inspect(bytes(corrupt))
