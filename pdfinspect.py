#!/usr/bin/env python3
import sys
import os
import re
import zlib
import json
import struct
import argparse
from io import BytesIO
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any, Union


class PDFObject:
    pass


class PDFNull(PDFObject):
    def __repr__(self):
        return "null"

    def __eq__(self, other):
        return isinstance(other, PDFNull)


class PDFBoolean(PDFObject):
    def __init__(self, value: bool):
        self.value = value

    def __repr__(self):
        return "true" if self.value else "false"

    def __bool__(self):
        return self.value


class PDFNumber(PDFObject):
    def __init__(self, value: Union[int, float]):
        self.value = value

    def __repr__(self):
        return str(self.value)

    def __int__(self):
        return int(self.value)

    def __float__(self):
        return float(self.value)


class PDFName(PDFObject):
    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return "/" + self.name

    def __eq__(self, other):
        if isinstance(other, PDFName):
            return self.name == other.name
        return False

    def __hash__(self):
        return hash(self.name)


class PDFString(PDFObject):
    def __init__(self, value: bytes, is_hex: bool = False):
        self.value = value
        self.is_hex = is_hex

    def __repr__(self):
        return repr(self.value)

    def decode(self, encoding='latin-1'):
        try:
            return self.value.decode(encoding)
        except:
            return self.value.decode('latin-1', errors='replace')


class PDFArray(PDFObject):
    def __init__(self, items: List[PDFObject]):
        self.items = items

    def __repr__(self):
        return "[" + ", ".join(repr(i) for i in self.items) + "]"

    def __getitem__(self, idx):
        return self.items[idx]

    def __len__(self):
        return len(self.items)

    def __iter__(self):
        return iter(self.items)


class PDFDict(PDFObject):
    def __init__(self, items: Dict[PDFName, PDFObject]):
        self._items = items

    def __repr__(self):
        return "<<" + ", ".join(f"{k}: {v}" for k, v in self._items.items()) + ">>"

    @staticmethod
    def _normalize_key(key):
        if isinstance(key, str):
            if key.startswith('/'):
                key = key[1:]
            return PDFName(key)
        return key

    def __getitem__(self, key):
        return self._items[self._normalize_key(key)]

    def __contains__(self, key):
        return self._normalize_key(key) in self._items

    def get(self, key, default=None):
        return self._items.get(self._normalize_key(key), default)

    def keys(self):
        return self._items.keys()

    def values(self):
        return self._items.values()

    def items(self):
        return self._items.items()


class PDFStream(PDFObject):
    def __init__(self, dict_obj: PDFDict, data: bytes):
        self.dict = dict_obj
        self.data = data

    def __repr__(self):
        return f"Stream({self.dict}, data_len={len(self.data)})"

    def get_filtered_data(self) -> bytes:
        data = self.data
        if 'Filter' not in self.dict:
            return data
        filters = self.dict['Filter']
        if isinstance(filters, PDFName):
            filters = [filters]
        else:
            filters = filters.items
        for f in filters:
            if f.name == 'FlateDecode':
                data = zlib.decompress(data)
            elif f.name == 'ASCIIHexDecode':
                data = ascii_hex_decode(data)
            elif f.name == 'ASCII85Decode':
                data = ascii_85_decode(data)
            elif f.name == 'DCTDecode':
                pass
        return data


class PDFIndirectRef(PDFObject):
    def __init__(self, obj_num: int, gen_num: int):
        self.obj_num = obj_num
        self.gen_num = gen_num

    def __repr__(self):
        return f"{self.obj_num} {self.gen_num} R"

    def __eq__(self, other):
        if isinstance(other, PDFIndirectRef):
            return self.obj_num == other.obj_num and self.gen_num == other.gen_num
        return False

    def __hash__(self):
        return hash((self.obj_num, self.gen_num))


class PDFIndirectObject(PDFObject):
    def __init__(self, obj_num: int, gen_num: int, obj: PDFObject):
        self.obj_num = obj_num
        self.gen_num = gen_num
        self.obj = obj

    def __repr__(self):
        return f"{self.obj_num} {self.gen_num} obj\n{self.obj}\nendobj"


def ascii_hex_decode(data: bytes) -> bytes:
    result = bytearray()
    hex_chars = []
    for b in data:
        c = chr(b)
        if c.isspace():
            continue
        if c == '>':
            break
        hex_chars.append(c)
    if len(hex_chars) % 2 == 1:
        hex_chars.append('0')
    for i in range(0, len(hex_chars), 2):
        result.append(int(''.join(hex_chars[i:i + 2]), 16))
    return bytes(result)


def ascii_85_decode(data: bytes) -> bytes:
    result = bytearray()
    group = []
    for b in data:
        c = chr(b)
        if c.isspace():
            continue
        if c == '~':
            break
        if c == 'z' and len(group) == 0:
            result.extend(b'\x00\x00\x00\x00')
            continue
        group.append(ord(c) - 33)
        if len(group) == 5:
            val = 0
            for g in group:
                val = val * 85 + g
            result.extend(struct.pack('>I', val))
            group = []
    if group:
        while len(group) < 5:
            group.append(84)
        val = 0
        for g in group:
            val = val * 85 + g
        result.extend(struct.pack('>I', val)[:len(group) - 1])
    return bytes(result)


class Lexer:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.len = len(data)

    def peek(self, n=1):
        if self.pos + n > self.len:
            return self.data[self.pos:]
        return self.data[self.pos:self.pos + n]

    def advance(self, n=1):
        self.pos += n

    def skip_whitespace(self):
        while self.pos < self.len:
            b = self.data[self.pos]
            if b in (0x00, 0x09, 0x0A, 0x0C, 0x0D, 0x20):
                self.pos += 1
            elif self.data[self.pos:self.pos + 1] == b'%':
                while self.pos < self.len and self.data[self.pos:self.pos + 1] != b'\n' and self.data[self.pos:self.pos + 1] != b'\r':
                    self.pos += 1
            else:
                break

    def eof(self):
        return self.pos >= self.len

    def next_token(self):
        self.skip_whitespace()
        if self.eof():
            return None, None

        start = self.pos
        b = self.data[self.pos]

        if b == ord('('):
            return self._read_literal_string()
        elif b == ord('<'):
            if self.pos + 1 < self.len and self.data[self.pos + 1] == ord('<'):
                self.advance(2)
                return 'DICT_START', None
            else:
                return self._read_hex_string()
        elif b == ord('>'):
            if self.pos + 1 < self.len and self.data[self.pos + 1] == ord('>'):
                self.advance(2)
                return 'DICT_END', None
            else:
                self.advance()
                return 'OTHER', b'>'
        elif b == ord('['):
            self.advance()
            return 'ARRAY_START', None
        elif b == ord(']'):
            self.advance()
            return 'ARRAY_END', None
        elif b == ord('/'):
            return self._read_name()
        elif b == ord('{') or b == ord('}'):
            self.advance()
            return 'OTHER', chr(b)
        else:
            return self._read_other()

    def _read_literal_string(self):
        self.advance()
        result = bytearray()
        depth = 1
        while self.pos < self.len and depth > 0:
            b = self.data[self.pos]
            if b == ord('\\') and self.pos + 1 < self.len:
                self.advance()
                nb = self.data[self.pos]
                escapes = {ord('n'): b'\n', ord('r'): b'\r', ord('t'): b'\t',
                           ord('b'): b'\b', ord('f'): b'\f', ord('('): b'(',
                           ord(')'): b')', ord('\\'): b'\\'}
                if nb in escapes:
                    result.extend(escapes[nb])
                elif ord('0') <= nb <= ord('7'):
                    octal = chr(nb)
                    for _ in range(2):
                        if self.pos + 1 < self.len and ord('0') <= self.data[self.pos + 1] <= ord('7'):
                            self.advance()
                            octal += chr(self.data[self.pos])
                        else:
                            break
                    result.append(int(octal, 8))
                elif nb == ord('\n') or nb == ord('\r'):
                    if nb == ord('\r') and self.pos + 1 < self.len and self.data[self.pos + 1] == ord('\n'):
                        self.advance()
                else:
                    result.append(nb)
            elif b == ord('('):
                depth += 1
                result.append(b)
            elif b == ord(')'):
                depth -= 1
                if depth == 0:
                    self.advance()
                    break
                result.append(b)
            elif b == ord('\r') and self.pos + 1 < self.len and self.data[self.pos + 1] == ord('\n'):
                result.extend(b'\n')
                self.advance()
            else:
                result.append(b)
            self.advance()
        return 'STRING', PDFString(bytes(result), is_hex=False)

    def _read_hex_string(self):
        self.advance()
        hex_data = bytearray()
        while self.pos < self.len:
            b = self.data[self.pos]
            if b == ord('>'):
                self.advance()
                break
            if chr(b).isspace():
                self.advance()
                continue
            hex_data.append(b)
            self.advance()
        return 'STRING', PDFString(ascii_hex_decode(bytes(hex_data)), is_hex=True)

    def _read_name(self):
        self.advance()
        name = bytearray()
        while self.pos < self.len:
            b = self.data[self.pos]
            if b in (0x00, 0x09, 0x0A, 0x0C, 0x0D, 0x20) or b in (ord('('), ord(')'), ord('<'), ord('>'), ord('['), ord(']'), ord('{'), ord('}'), ord('/'), ord('%')):
                break
            if b == ord('#') and self.pos + 2 < self.len:
                hex_str = bytes(self.data[self.pos + 1:self.pos + 3])
                try:
                    name.append(int(hex_str.decode(), 16))
                    self.advance(3)
                    continue
                except:
                    pass
            name.append(b)
            self.advance()
        return 'NAME', PDFName(name.decode('latin-1'))

    def _read_other(self):
        start = self.pos
        while self.pos < self.len:
            b = self.data[self.pos]
            if b in (0x00, 0x09, 0x0A, 0x0C, 0x0D, 0x20) or b in (ord('('), ord(')'), ord('<'), ord('>'), ord('['), ord(']'), ord('{'), ord('}'), ord('/'), ord('%')):
                break
            self.advance()
        token = self.data[start:self.pos].decode('latin-1')
        if not token:
            return None, None
        if token == 'true':
            return 'BOOLEAN', PDFBoolean(True)
        if token == 'false':
            return 'BOOLEAN', PDFBoolean(False)
        if token == 'null':
            return 'NULL', PDFNull()
        if token == 'obj':
            return 'OBJ', None
        if token == 'endobj':
            return 'ENDOBJ', None
        if token == 'stream':
            return 'STREAM', None
        if token == 'endstream':
            return 'ENDSTREAM', None
        if token == 'R':
            return 'REF', None
        if re.match(r'^[+-]?\d+$', token):
            return 'NUMBER', PDFNumber(int(token))
        if re.match(r'^[+-]?(\d+\.\d*|\.\d+)([eE][+-]?\d+)?$', token) or re.match(r'^[+-]?\d+[eE][+-]?\d+$', token):
            return 'NUMBER', PDFNumber(float(token))
        return 'KEYWORD', token


class Parser:
    def __init__(self, data: bytes, doc: 'PDFDocument' = None):
        self.lexer = Lexer(data)
        self.doc = doc
        self._peeked = None

    def peek_token(self):
        if self._peeked is None:
            self._peeked = self.lexer.next_token()
        return self._peeked

    def next_token(self):
        if self._peeked is not None:
            tok = self._peeked
            self._peeked = None
            return tok
        return self.lexer.next_token()

    def parse_object(self) -> PDFObject:
        tok_type, tok_val = self.next_token()
        if tok_type is None:
            return PDFNull()
        if tok_type == 'DICT_START':
            return self._parse_dict()
        if tok_type == 'ARRAY_START':
            return self._parse_array()
        if tok_type == 'NUMBER':
            ref = self._parse_ref(tok_val)
            if ref is not None:
                return ref
            return tok_val
        if tok_type in ('STRING', 'NAME', 'BOOLEAN', 'NULL'):
            return tok_val
        if tok_type == 'KEYWORD':
            return PDFName(tok_val) if False else tok_val
        return PDFNull()

    def _parse_dict(self) -> PDFDict:
        items = {}
        while True:
            tok_type, tok_val = self.peek_token()
            if tok_type == 'DICT_END' or tok_type is None:
                self.next_token()
                break
            if tok_type == 'NAME':
                self.next_token()
                key = tok_val
                val = self.parse_object()
                items[key] = val
            else:
                self.next_token()
        return PDFDict(items)

    def _parse_array(self) -> PDFArray:
        items = []
        while True:
            tok_type, tok_val = self.peek_token()
            if tok_type == 'ARRAY_END' or tok_type is None:
                self.next_token()
                break
            items.append(self.parse_object())
        return PDFArray(items)

    def _parse_ref(self, first_num: PDFNumber) -> Optional[PDFIndirectRef]:
        if not isinstance(first_num.value, int):
            return None
        tok_type2, tok_val2 = self.peek_token()
        if tok_type2 != 'NUMBER' or not isinstance(tok_val2.value, int):
            return None
        saved_pos = self.lexer.pos
        saved_peeked = self._peeked
        self.next_token()
        tok_type3, tok_val3 = self.peek_token()
        if tok_type3 == 'REF':
            self.next_token()
            return PDFIndirectRef(first_num.value, tok_val2.value)
        self.lexer.pos = saved_pos
        self._peeked = saved_peeked
        return None

    def parse_indirect_object(self) -> Optional[PDFIndirectObject]:
        tok_type1, tok_val1 = self.next_token()
        if tok_type1 != 'NUMBER' or not isinstance(tok_val1.value, int):
            return None
        obj_num = tok_val1.value
        tok_type2, tok_val2 = self.next_token()
        if tok_type2 != 'NUMBER' or not isinstance(tok_val2.value, int):
            return None
        gen_num = tok_val2.value
        tok_type3, _ = self.next_token()
        if tok_type3 != 'OBJ':
            return None
        obj = self.parse_object()
        tok_type4, _ = self.peek_token()
        if tok_type4 == 'STREAM':
            self.next_token()
            stream_data = self._read_stream_data(obj)
            obj = PDFStream(obj if isinstance(obj, PDFDict) else PDFDict({}), stream_data)
        tok_type5, _ = self.peek_token()
        if tok_type5 == 'ENDOBJ':
            self.next_token()
        return PDFIndirectObject(obj_num, gen_num, obj)

    def _read_stream_data(self, dict_obj: PDFDict) -> bytes:
        while self.lexer.pos < self.lexer.len:
            b = self.lexer.data[self.lexer.pos]
            if b == ord('\n'):
                self.lexer.advance()
                break
            if b == ord('\r'):
                self.lexer.advance()
                if self.lexer.pos < self.lexer.len and self.lexer.data[self.lexer.pos] == ord('\n'):
                    self.lexer.advance()
                break
            self.lexer.advance()
        length = 0
        if isinstance(dict_obj, PDFDict) and 'Length' in dict_obj:
            len_obj = dict_obj['Length']
            if isinstance(len_obj, PDFIndirectRef) and self.doc:
                len_obj = self.doc.resolve(len_obj)
            if isinstance(len_obj, PDFNumber):
                length = int(len_obj.value)
        if length > 0:
            data = self.lexer.data[self.lexer.pos:self.lexer.pos + length]
            self.lexer.advance(length)
        else:
            start = self.lexer.pos
            endstream_pattern = b'endstream'
            idx = self.lexer.data.find(endstream_pattern, start)
            if idx == -1:
                data = self.lexer.data[start:]
                self.lexer.pos = self.lexer.len
            else:
                data = self.lexer.data[start:idx]
                if data.endswith(b'\r\n'):
                    data = data[:-2]
                elif data.endswith(b'\n') or data.endswith(b'\r'):
                    data = data[:-1]
                self.lexer.pos = idx
        return data


@dataclass
class XRefEntry:
    obj_num: int
    offset: int
    gen_num: int
    in_use: bool
    is_compressed: bool = False
    stream_num: int = 0

    def __repr__(self):
        if self.is_compressed:
            return f"[{self.obj_num}] compressed in stream {self.stream_num}, index {self.offset}"
        if self.in_use:
            return f"[{self.obj_num}] offset={self.offset}, gen={self.gen_num}"
        return f"[{self.obj_num}] free, next={self.offset}, gen={self.gen_num}"


@dataclass
class PDFPage:
    page_num: int
    obj: PDFObject
    ref: PDFIndirectRef
    mediabox: Optional[List[float]] = None
    cropbox: Optional[List[float]] = None
    resources: Optional[PDFDict] = None
    contents: List[PDFIndirectRef] = field(default_factory=list)
    text: str = ""
    text_blocks: List[Dict] = field(default_factory=list)


class PDFDocument:
    def __init__(self, path: str):
        self.path = path
        with open(path, 'rb') as f:
            self.data = f.read()
        self.header = ""
        self.version = ""
        self.trailer: Optional[PDFDict] = None
        self.xref_entries: Dict[int, XRefEntry] = {}
        self.objects: Dict[Tuple[int, int], PDFObject] = {}
        self.catalog_ref: Optional[PDFIndirectRef] = None
        self.catalog: Optional[PDFDict] = None
        self.pages: List[PDFPage] = []
        self._parse()

    def _parse(self):
        self._parse_header()
        self._parse_xref_and_trailer()
        if '/Root' in self.trailer:
            self.catalog_ref = self.trailer['/Root']
            self.catalog = self.resolve(self.catalog_ref)
        self._resolve_all_objects()
        self._parse_pages()

    def _parse_header(self):
        if not self.data.startswith(b'%PDF-'):
            raise ValueError("Not a valid PDF file")
        nl = self.data.find(b'\n', 0)
        if nl == -1:
            nl = len(self.data)
        header_line = self.data[:nl].decode('latin-1').strip()
        self.header = header_line
        self.version = header_line[5:] if len(header_line) > 5 else ""

    def _parse_xref_and_trailer(self):
        eof_marker = b'%%EOF'
        startxref_marker = b'startxref'
        eof_pos = self.data.rfind(eof_marker)
        if eof_pos == -1:
            raise ValueError("No %%EOF found")
        startxref_pos = self.data.rfind(startxref_marker, 0, eof_pos)
        if startxref_pos == -1:
            raise ValueError("No startxref found")
        xref_offset_str = self.data[startxref_pos + len(startxref_marker):eof_pos].strip()
        xref_offset = int(xref_offset_str.decode())
        self._parse_xref_at(xref_offset)

    def _parse_xref_at(self, offset: int):
        parser = Parser(self.data[offset:])
        tok_type, tok_val = parser.peek_token()
        if tok_type == 'KEYWORD' and tok_val == 'xref':
            self._parse_xref_table(offset)
        elif tok_type == 'NUMBER':
            self._parse_xref_stream(offset)

    def _parse_xref_table(self, offset: int):
        pos = offset
        if self.data[pos:pos + 4] != b'xref':
            return
        pos += 4
        while self.data[pos:pos + 1] in (b' ', b'\t', b'\n', b'\r'):
            pos += 1
        while True:
            line_end = self.data.find(b'\n', pos)
            if line_end == -1:
                line_end = len(self.data)
            line = self.data[pos:line_end].strip()
            if line == b'trailer':
                pos = line_end + 1
                break
            parts = line.split()
            if len(parts) != 2:
                pos = line_end + 1
                continue
            try:
                start_obj = int(parts[0])
                count = int(parts[1])
            except:
                pos = line_end + 1
                continue
            pos = line_end + 1
            for i in range(count):
                obj_num = start_obj + i
                entry_end = self.data.find(b'\n', pos)
                if entry_end == -1:
                    entry_end = len(self.data)
                entry_line = self.data[pos:entry_end].strip()
                pos = entry_end + 1
                entry_parts = entry_line.split()
                if len(entry_parts) != 3:
                    continue
                try:
                    off = int(entry_parts[0])
                    gen = int(entry_parts[1])
                    in_use = entry_parts[2] == b'n'
                    self.xref_entries[obj_num] = XRefEntry(obj_num, off, gen, in_use)
                except:
                    continue
        trailer_parser = Parser(self.data[pos:])
        trailer_dict = trailer_parser.parse_object()
        if isinstance(trailer_dict, PDFDict):
            self.trailer = trailer_dict
        if 'XRefStm' in trailer_dict:
            xrefstm_ref = trailer_dict['XRefStm']
            if isinstance(xrefstm_ref, PDFNumber):
                self._parse_xref_stream(int(xrefstm_ref.value))
        if 'Prev' in trailer_dict:
            prev_ref = trailer_dict['Prev']
            if isinstance(prev_ref, PDFNumber):
                self._parse_xref_at(int(prev_ref.value))

    def _parse_xref_stream(self, offset: int):
        obj_parser = Parser(self.data[offset:], self)
        ind_obj = obj_parser.parse_indirect_object()
        if not ind_obj or not isinstance(ind_obj.obj, PDFStream):
            return
        stream = ind_obj.obj
        stream_data = stream.get_filtered_data()
        w = []
        if '/W' in stream.dict:
            w = [int(n.value) for n in stream.dict['/W']]
        size = 1
        if '/Size' in stream.dict:
            size = int(stream.dict['/Size'].value)
        index = [(0, size)]
        if '/Index' in stream.dict:
            idx_arr = stream.dict['/Index']
            index = []
            for i in range(0, len(idx_arr), 2):
                index.append((int(idx_arr[i].value), int(idx_arr[i + 1].value)))
        entry_size = sum(w)
        data_pos = 0
        for start, count in index:
            for i in range(count):
                obj_num = start + i
                entry = stream_data[data_pos:data_pos + entry_size]
                data_pos += entry_size
                if len(entry) < entry_size:
                    continue
                fields = []
                p = 0
                for j in range(3):
                    if w[j] == 0:
                        fields.append(1 if j == 0 else 0)
                    else:
                        val = 0
                        for k in range(w[j]):
                            val = (val << 8) | entry[p]
                            p += 1
                        fields.append(val)
                ftype, f1, f2 = fields[0], fields[1], fields[2]
                if ftype == 0:
                    self.xref_entries[obj_num] = XRefEntry(obj_num, f1, f2, False)
                elif ftype == 1:
                    self.xref_entries[obj_num] = XRefEntry(obj_num, f1, f2, True)
                elif ftype == 2:
                    xentry = XRefEntry(obj_num, f2, 0, True, True, f1)
                    self.xref_entries[obj_num] = xentry
        if '/Root' in stream.dict and self.trailer is None:
            self.trailer = stream.dict
        if 'Prev' in stream.dict:
            prev_ref = stream.dict['Prev']
            if isinstance(prev_ref, PDFNumber):
                self._parse_xref_at(int(prev_ref.value))

    def _resolve_all_objects(self):
        for obj_num, entry in self.xref_entries.items():
            if not entry.in_use or entry.is_compressed:
                continue
            try:
                parser = Parser(self.data[entry.offset:], self)
                ind_obj = parser.parse_indirect_object()
                if ind_obj:
                    self.objects[(obj_num, ind_obj.gen_num)] = ind_obj.obj
            except Exception as e:
                pass

    def resolve(self, ref: PDFIndirectRef) -> PDFObject:
        if not isinstance(ref, PDFIndirectRef):
            return ref
        key = (ref.obj_num, ref.gen_num)
        if key in self.objects:
            return self.objects[key]
        if ref.obj_num in self.xref_entries:
            entry = self.xref_entries[ref.obj_num]
            if entry.in_use and not entry.is_compressed:
                try:
                    parser = Parser(self.data[entry.offset:], self)
                    ind_obj = parser.parse_indirect_object()
                    if ind_obj:
                        self.objects[key] = ind_obj.obj
                        return ind_obj.obj
                except:
                    pass
            if entry.is_compressed:
                return self._resolve_compressed(entry)
        return PDFNull()

    def _resolve_compressed(self, entry: XRefEntry) -> PDFObject:
        stream_obj_key = (entry.stream_num, 0)
        if stream_obj_key not in self.objects:
            if entry.stream_num in self.xref_entries:
                sref_entry = self.xref_entries[entry.stream_num]
                parser = Parser(self.data[sref_entry.offset:], self)
                ind_obj = parser.parse_indirect_object()
                if ind_obj:
                    self.objects[stream_obj_key] = ind_obj.obj
        if stream_obj_key not in self.objects:
            return PDFNull()
        stream = self.objects[stream_obj_key]
        if not isinstance(stream, PDFStream):
            return PDFNull()
        data = stream.get_filtered_data()
        parser = Parser(data, self)
        obj_idx = entry.offset
        count_arr = stream.dict.get('N', None)
        if isinstance(count_arr, PDFNumber):
            pass
        idx_arr = stream.dict.get('Index', None)
        offsets = None
        if 'W' in stream.dict:
            pass
        for i in range(obj_idx + 1):
            try:
                obj = parser.parse_object()
                if i == obj_idx:
                    return obj
            except:
                break
        return PDFNull()

    def _parse_pages(self):
        if not self.catalog or '/Pages' not in self.catalog:
            return
        pages_root = self.resolve(self.catalog['/Pages'])
        page_num = [0]
        self._walk_pages(pages_root, page_num)

    def _walk_pages(self, pages_obj, page_num_counter):
        if isinstance(pages_obj, PDFIndirectRef):
            pages_obj = self.resolve(pages_obj)
        if not isinstance(pages_obj, PDFDict):
            return
        obj_type = pages_obj.get('/Type', None)
        type_name = obj_type.name if isinstance(obj_type, PDFName) else ""
        if type_name == 'Page':
            page_num_counter[0] += 1
            page_ref = None
            for k, v in self.objects.items():
                if v is pages_obj:
                    page_ref = PDFIndirectRef(k[0], k[1])
                    break
            page = PDFPage(page_num_counter[0], pages_obj, page_ref)
            if '/MediaBox' in pages_obj:
                mb = pages_obj['/MediaBox']
                if isinstance(mb, PDFArray):
                    page.mediabox = [float(x.value) for x in mb]
            if '/CropBox' in pages_obj:
                cb = pages_obj['/CropBox']
                if isinstance(cb, PDFArray):
                    page.cropbox = [float(x.value) for x in cb]
            if '/Resources' in pages_obj:
                res = self.resolve(pages_obj['/Resources'])
                if isinstance(res, PDFDict):
                    page.resources = res
            if '/Contents' in pages_obj:
                c = pages_obj['/Contents']
                if isinstance(c, PDFIndirectRef):
                    page.contents = [c]
                elif isinstance(c, PDFArray):
                    page.contents = [r for r in c if isinstance(r, PDFIndirectRef)]
            self.pages.append(page)
        elif type_name == 'Pages':
            if '/Kids' in pages_obj:
                kids = pages_obj['/Kids']
                if isinstance(kids, PDFArray):
                    for kid in kids:
                        self._walk_pages(kid, page_num_counter)

    def get_page_content(self, page: PDFPage) -> bytes:
        contents = []
        for ref in page.contents:
            obj = self.resolve(ref)
            if isinstance(obj, PDFStream):
                try:
                    contents.append(obj.get_filtered_data())
                except:
                    pass
        return b'\n'.join(contents)

    def list_all_objects_by_type(self, type_name: str) -> List[Tuple[PDFIndirectRef, PDFObject]]:
        result = []
        for (obj_num, gen), obj in self.objects.items():
            if isinstance(obj, PDFDict) and '/Type' in obj:
                t = obj['/Type']
                if isinstance(t, PDFName) and t.name == type_name:
                    result.append((PDFIndirectRef(obj_num, gen), obj))
            elif isinstance(obj, PDFStream) and '/Type' in obj.dict:
                t = obj.dict['/Type']
                if isinstance(t, PDFName) and t.name == type_name:
                    result.append((PDFIndirectRef(obj_num, gen), obj))
        return result

    def list_xobjects(self, subtype: str = None) -> List[Tuple[PDFIndirectRef, PDFStream]]:
        result = []
        for (obj_num, gen), obj in self.objects.items():
            if isinstance(obj, PDFStream) and '/Type' in obj.dict:
                t = obj.dict['/Type']
                if isinstance(t, PDFName) and t.name == 'XObject':
                    if subtype is None:
                        result.append((PDFIndirectRef(obj_num, gen), obj))
                    elif '/Subtype' in obj.dict:
                        st = obj.dict['/Subtype']
                        if isinstance(st, PDFName) and st.name == subtype:
                            result.append((PDFIndirectRef(obj_num, gen), obj))
        return result


WIN_ANSI_ENCODING = {
    0x00: '\u0000', 0x01: '\u0001', 0x02: '\u0002', 0x03: '\u0003',
    0x04: '\u0004', 0x05: '\u0005', 0x06: '\u0006', 0x07: '\u0007',
    0x08: '\u0008', 0x09: '\u0009', 0x0A: '\u000A', 0x0B: '\u000B',
    0x0C: '\u000C', 0x0D: '\u000D', 0x0E: '\u000E', 0x0F: '\u000F',
    0x10: '\u0010', 0x11: '\u0011', 0x12: '\u0012', 0x13: '\u0013',
    0x14: '\u0014', 0x15: '\u0015', 0x16: '\u0016', 0x17: '\u0017',
    0x18: '\u0018', 0x19: '\u0019', 0x1A: '\u001A', 0x1B: '\u001B',
    0x1C: '\u001C', 0x1D: '\u001D', 0x1E: '\u001E', 0x1F: '\u001F',
    0x20: ' ', 0x21: '!', 0x22: '"', 0x23: '#',
    0x24: '$', 0x25: '%', 0x26: '&', 0x27: "'",
    0x28: '(', 0x29: ')', 0x2A: '*', 0x2B: '+',
    0x2C: ',', 0x2D: '-', 0x2E: '.', 0x2F: '/',
    0x30: '0', 0x31: '1', 0x32: '2', 0x33: '3',
    0x34: '4', 0x35: '5', 0x36: '6', 0x37: '7',
    0x38: '8', 0x39: '9', 0x3A: ':', 0x3B: ';',
    0x3C: '<', 0x3D: '=', 0x3E: '>', 0x3F: '?',
    0x40: '@', 0x41: 'A', 0x42: 'B', 0x43: 'C',
    0x44: 'D', 0x45: 'E', 0x46: 'F', 0x47: 'G',
    0x48: 'H', 0x49: 'I', 0x4A: 'J', 0x4B: 'K',
    0x4C: 'L', 0x4D: 'M', 0x4E: 'N', 0x4F: 'O',
    0x50: 'P', 0x51: 'Q', 0x52: 'R', 0x53: 'S',
    0x54: 'T', 0x55: 'U', 0x56: 'V', 0x57: 'W',
    0x58: 'X', 0x59: 'Y', 0x5A: 'Z', 0x5B: '[',
    0x5C: '\\', 0x5D: ']', 0x5E: '^', 0x5F: '_',
    0x60: '`', 0x61: 'a', 0x62: 'b', 0x63: 'c',
    0x64: 'd', 0x65: 'e', 0x66: 'f', 0x67: 'g',
    0x68: 'h', 0x69: 'i', 0x6A: 'j', 0x6B: 'k',
    0x6C: 'l', 0x6D: 'm', 0x6E: 'n', 0x6F: 'o',
    0x70: 'p', 0x71: 'q', 0x72: 'r', 0x73: 's',
    0x74: 't', 0x75: 'u', 0x76: 'v', 0x77: 'w',
    0x78: 'x', 0x79: 'y', 0x7A: 'z', 0x7B: '{',
    0x7C: '|', 0x7D: '}', 0x7E: '~', 0x7F: '\u007F',
    0x80: '\u20AC', 0x81: '', 0x82: '\u201A', 0x83: '\u0192',
    0x84: '\u201E', 0x85: '\u2026', 0x86: '\u2020', 0x87: '\u2021',
    0x88: '\u02C6', 0x89: '\u2030', 0x8A: '\u0160', 0x8B: '\u2039',
    0x8C: '\u0152', 0x8D: '', 0x8E: '\u017D', 0x8F: '',
    0x90: '', 0x91: '\u2018', 0x92: '\u2019', 0x93: '\u201C',
    0x94: '\u201D', 0x95: '\u2022', 0x96: '\u2013', 0x97: '\u2014',
    0x98: '\u02DC', 0x99: '\u2122', 0x9A: '\u0161', 0x9B: '\u203A',
    0x9C: '\u0153', 0x9D: '', 0x9E: '\u017E', 0x9F: '\u0178',
    0xA0: '\u00A0', 0xA1: '\u00A1', 0xA2: '\u00A2', 0xA3: '\u00A3',
    0xA4: '\u00A4', 0xA5: '\u00A5', 0xA6: '\u00A6', 0xA7: '\u00A7',
    0xA8: '\u00A8', 0xA9: '\u00A9', 0xAA: '\u00AA', 0xAB: '\u00AB',
    0xAC: '\u00AC', 0xAD: '\u00AD', 0xAE: '\u00AE', 0xAF: '\u00AF',
    0xB0: '\u00B0', 0xB1: '\u00B1', 0xB2: '\u00B2', 0xB3: '\u00B3',
    0xB4: '\u00B4', 0xB5: '\u00B5', 0xB6: '\u00B6', 0xB7: '\u00B7',
    0xB8: '\u00B8', 0xB9: '\u00B9', 0xBA: '\u00BA', 0xBB: '\u00BB',
    0xBC: '\u00BC', 0xBD: '\u00BD', 0xBE: '\u00BE', 0xBF: '\u00BF',
    0xC0: '\u00C0', 0xC1: '\u00C1', 0xC2: '\u00C2', 0xC3: '\u00C3',
    0xC4: '\u00C4', 0xC5: '\u00C5', 0xC6: '\u00C6', 0xC7: '\u00C7',
    0xC8: '\u00C8', 0xC9: '\u00C9', 0xCA: '\u00CA', 0xCB: '\u00CB',
    0xCC: '\u00CC', 0xCD: '\u00CD', 0xCE: '\u00CE', 0xCF: '\u00CF',
    0xD0: '\u00D0', 0xD1: '\u00D1', 0xD2: '\u00D2', 0xD3: '\u00D3',
    0xD4: '\u00D4', 0xD5: '\u00D5', 0xD6: '\u00D6', 0xD7: '\u00D7',
    0xD8: '\u00D8', 0xD9: '\u00D9', 0xDA: '\u00DA', 0xDB: '\u00DB',
    0xDC: '\u00DC', 0xDD: '\u00DD', 0xDE: '\u00DE', 0xDF: '\u00DF',
    0xE0: '\u00E0', 0xE1: '\u00E1', 0xE2: '\u00E2', 0xE3: '\u00E3',
    0xE4: '\u00E4', 0xE5: '\u00E5', 0xE6: '\u00E6', 0xE7: '\u00E7',
    0xE8: '\u00E8', 0xE9: '\u00E9', 0xEA: '\u00EA', 0xEB: '\u00EB',
    0xEC: '\u00EC', 0xED: '\u00ED', 0xEE: '\u00EE', 0xEF: '\u00EF',
    0xF0: '\u00F0', 0xF1: '\u00F1', 0xF2: '\u00F2', 0xF3: '\u00F3',
    0xF4: '\u00F4', 0xF5: '\u00F5', 0xF6: '\u00F6', 0xF7: '\u00F7',
    0xF8: '\u00F8', 0xF9: '\u00F9', 0xFA: '\u00FA', 0xFB: '\u00FB',
    0xFC: '\u00FC', 0xFD: '\u00FD', 0xFE: '\u00FE', 0xFF: '\u00FF',
}


class ContentStreamParser:
    def __init__(self, doc: PDFDocument, page: PDFPage):
        self.doc = doc
        self.page = page
        self.text_blocks = []
        self.current_text = ""
        self.font_map = {}
        self.current_font = None
        self.current_font_size = 12
        self.tm = [1, 0, 0, 1, 0, 0]
        self.td_y = 0
        self._in_text = False

    def parse(self, data: bytes):
        self.fonts = {}
        if self.page.resources and '/Font' in self.page.resources:
            fonts_dict = self.page.resources['/Font']
            if isinstance(fonts_dict, PDFDict):
                for k, v in fonts_dict.items():
                    font_obj = self.doc.resolve(v)
                    self.fonts[k.name] = font_obj
        lexer = Lexer(data)
        operands = []
        while True:
            tok_type, tok_val = lexer.next_token()
            if tok_type is None:
                break
            if tok_type in ('NUMBER', 'STRING', 'NAME', 'BOOLEAN', 'NULL'):
                operands.append(tok_val)
            elif tok_type == 'ARRAY_START':
                arr = self._parse_array(lexer)
                operands.append(arr)
            elif tok_type == 'DICT_START':
                d = self._parse_dict(lexer)
                operands.append(d)
            elif tok_type == 'KEYWORD':
                self._handle_operator(tok_val, operands)
                operands = []
            elif tok_type == 'REF':
                if len(operands) >= 2:
                    gen = operands.pop()
                    num = operands.pop()
                    if isinstance(num, PDFNumber) and isinstance(gen, PDFNumber):
                        operands.append(PDFIndirectRef(int(num.value), int(gen.value)))
        return self.text_blocks

    def _parse_array(self, lexer):
        items = []
        while True:
            tok_type, tok_val = lexer.next_token()
            if tok_type == 'ARRAY_END' or tok_type is None:
                break
            if tok_type == 'ARRAY_START':
                items.append(self._parse_array(lexer))
            elif tok_type == 'DICT_START':
                items.append(self._parse_dict(lexer))
            else:
                items.append(tok_val)
        return PDFArray(items)

    def _parse_dict(self, lexer):
        items = {}
        while True:
            tok_type, tok_val = lexer.next_token()
            if tok_type == 'DICT_END' or tok_type is None:
                break
            if tok_type == 'NAME':
                key = tok_val
                val_t, val_v = lexer.next_token()
                items[key] = val_v
        return PDFDict(items)

    def _handle_operator(self, op: str, operands):
        if op == 'BT':
            self._in_text = True
            self.current_text = ""
            self.tm = [1, 0, 0, 1, 0, 0]
        elif op == 'ET':
            self._in_text = False
            if self.current_text:
                self.text_blocks.append({
                    'text': self.current_text,
                    'x': self.tm[4],
                    'y': self.tm[5],
                    'font': self.current_font,
                    'font_size': self.current_font_size,
                })
        elif op == 'Tf':
            if len(operands) >= 2:
                font_name = operands[0]
                if isinstance(font_name, PDFName):
                    self.current_font = font_name.name
                if isinstance(operands[1], PDFNumber):
                    self.current_font_size = float(operands[1].value)
        elif op == 'Td':
            if len(operands) >= 2:
                tx = float(operands[0].value) if isinstance(operands[0], PDFNumber) else 0
                ty = float(operands[1].value) if isinstance(operands[1], PDFNumber) else 0
                self.tm[4] += tx
                self.tm[5] += ty
        elif op == 'TD':
            if len(operands) >= 2:
                tx = float(operands[0].value) if isinstance(operands[0], PDFNumber) else 0
                ty = float(operands[1].value) if isinstance(operands[1], PDFNumber) else 0
                self.tm[4] += tx
                self.tm[5] += ty
        elif op == 'Tm':
            if len(operands) >= 6:
                self.tm = [float(o.value) if isinstance(o, PDFNumber) else 0 for o in operands[:6]]
        elif op == 'T*':
            self.tm[5] -= self.current_font_size
        elif op == 'Tj':
            if operands and isinstance(operands[0], PDFString):
                text = self._decode_string(operands[0])
                self.current_text += text
        elif op == 'TJ':
            if operands and isinstance(operands[0], PDFArray):
                for item in operands[0]:
                    if isinstance(item, PDFString):
                        text = self._decode_string(item)
                        self.current_text += text
                    elif isinstance(item, PDFNumber):
                        val = float(item.value)
                        if val < -50:
                            self.current_text += ' '
        elif op == "'":
            if operands and isinstance(operands[0], PDFString):
                self.tm[5] -= self.current_font_size
                self.current_text += '\n'
                self.current_text += self._decode_string(operands[0])
        elif op == '"':
            if len(operands) >= 3 and isinstance(operands[2], PDFString):
                self.tm[5] -= self.current_font_size
                self.current_text += '\n'
                self.current_text += self._decode_string(operands[2])

    def _decode_string(self, s: PDFString) -> str:
        if self.current_font and self.current_font in self.fonts:
            font_obj = self.fonts[self.current_font]
            return self._decode_with_font(s, font_obj)
        return self._decode_simple(s)

    def _decode_with_font(self, s: PDFString, font_obj) -> str:
        if isinstance(font_obj, PDFDict) and '/ToUnicode' in font_obj:
            tounicode_ref = font_obj['/ToUnicode']
            tounicode = self.doc.resolve(tounicode_ref)
            if isinstance(tounicode, PDFStream):
                cmap = self._parse_tounicode(tounicode.get_filtered_data())
                if cmap:
                    result = []
                    i = 0
                    data = s.value
                    while i < len(data):
                        matched = False
                        for length in (2, 1):
                            if i + length <= len(data):
                                code = tuple(data[i:i + length])
                                if code in cmap:
                                    result.append(cmap[code])
                                    i += length
                                    matched = True
                                    break
                        if not matched:
                            result.append(chr(data[i]))
                            i += 1
                    return ''.join(result)
        if isinstance(font_obj, PDFDict) and '/Encoding' in font_obj:
            enc = font_obj['/Encoding']
            if isinstance(enc, PDFName) and enc.name == 'WinAnsiEncoding':
                return self._decode_winansi(s)
            if isinstance(enc, PDFDict) and '/BaseEncoding' in enc:
                be = enc['/BaseEncoding']
                if isinstance(be, PDFName) and be.name == 'WinAnsiEncoding':
                    return self._decode_winansi(s, enc)
        return self._decode_simple(s)

    def _parse_tounicode(self, data: bytes) -> Dict[Tuple[int, ...], str]:
        cmap = {}
        try:
            text = data.decode('latin-1')
            bfchar_pattern = re.compile(r'beginbfchar\s*(.*?)\s*endbfchar', re.DOTALL)
            bfrange_pattern = re.compile(r'beginbfrange\s*(.*?)\s*endbfrange', re.DOTALL)
            for m in bfchar_pattern.finditer(text):
                block = m.group(1)
                for line in block.strip().split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    m2 = re.match(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', line)
                    if m2:
                        src = bytes.fromhex(m2.group(1))
                        dst = bytes.fromhex(m2.group(2))
                        try:
                            cmap[tuple(src)] = dst.decode('utf-16-be')
                        except:
                            try:
                                cmap[tuple(src)] = dst.decode('utf-8')
                            except:
                                cmap[tuple(src)] = dst.decode('latin-1')
            for m in bfrange_pattern.finditer(text):
                block = m.group(1)
                for line in block.strip().split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    m2 = re.match(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', line)
                    if m2:
                        src_start = int(m2.group(1), 16)
                        src_end = int(m2.group(2), 16)
                        dst_start = int(m2.group(3), 16)
                        for i in range(src_end - src_start + 1):
                            src = src_start + i
                            dst = dst_start + i
                            try:
                                src_bytes = src.to_bytes((src.bit_length() + 7) // 8 or 1, 'big')
                                cmap[tuple(src_bytes)] = chr(dst)
                            except:
                                pass
        except:
            pass
        return cmap

    def _decode_winansi(self, s: PDFString, enc_dict: PDFDict = None) -> str:
        result = []
        diff_map = {}
        if enc_dict and '/Differences' in enc_dict:
            diff = enc_dict['/Differences']
            if isinstance(diff, PDFArray):
                current_code = None
                for item in diff:
                    if isinstance(item, PDFNumber):
                        current_code = int(item.value)
                    elif isinstance(item, PDFName) and current_code is not None:
                        name = item.name
                        diff_map[current_code] = _glyph_name_to_unicode(name)
                        current_code += 1
        for b in s.value:
            if b in diff_map:
                result.append(diff_map[b])
            elif b in WIN_ANSI_ENCODING:
                result.append(WIN_ANSI_ENCODING[b])
            else:
                result.append(chr(b))
        return ''.join(result)

    def _decode_simple(self, s: PDFString) -> str:
        try:
            return s.value.decode('utf-8')
        except:
            return self._decode_winansi(s)


def _glyph_name_to_unicode(name: str) -> str:
    standard = {
        'A': 'A', 'B': 'B', 'C': 'C', 'D': 'D', 'E': 'E', 'F': 'F', 'G': 'G',
        'H': 'H', 'I': 'I', 'J': 'J', 'K': 'K', 'L': 'L', 'M': 'M', 'N': 'N',
        'O': 'O', 'P': 'P', 'Q': 'Q', 'R': 'R', 'S': 'S', 'T': 'T', 'U': 'U',
        'V': 'V', 'W': 'W', 'X': 'X', 'Y': 'Y', 'Z': 'Z',
        'a': 'a', 'b': 'b', 'c': 'c', 'd': 'd', 'e': 'e', 'f': 'f', 'g': 'g',
        'h': 'h', 'i': 'i', 'j': 'j', 'k': 'k', 'l': 'l', 'm': 'm', 'n': 'n',
        'o': 'o', 'p': 'p', 'q': 'q', 'r': 'r', 's': 's', 't': 't', 'u': 'u',
        'v': 'v', 'w': 'w', 'x': 'x', 'y': 'y', 'z': 'z',
        'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4',
        'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9',
        'space': ' ', 'exclam': '!', 'quotedbl': '"', 'numbersign': '#',
        'dollar': '$', 'percent': '%', 'ampersand': '&', 'quotesingle': "'",
        'parenleft': '(', 'parenright': ')', 'asterisk': '*', 'plus': '+',
        'comma': ',', 'hyphen': '-', 'period': '.', 'slash': '/',
        'colon': ':', 'semicolon': ';', 'less': '<', 'equal': '=', 'greater': '>',
        'question': '?', 'at': '@', 'bracketleft': '[', 'backslash': '\\',
        'bracketright': ']', 'asciicircum': '^', 'underscore': '_',
        'grave': '`', 'braceleft': '{', 'bar': '|', 'braceright': '}',
        'asciitilde': '~',
        'Adieresis': 'Ä', 'Odieresis': 'Ö', 'Udieresis': 'Ü',
        'adieresis': 'ä', 'odieresis': 'ö', 'udieresis': 'ü',
        'Aring': 'Å', 'aring': 'å', 'AE': 'Æ', 'ae': 'æ',
        'OE': 'Œ', 'oe': 'œ', 'Ccedilla': 'Ç', 'ccedilla': 'ç',
        'Ntilde': 'Ñ', 'ntilde': 'ñ',
        'Agrave': 'À', 'Aacute': 'Á', 'Acircumflex': 'Â', 'Atilde': 'Ã',
        'Egrave': 'È', 'Eacute': 'É', 'Ecircumflex': 'Ê', 'Edieresis': 'Ë',
        'Igrave': 'Ì', 'Iacute': 'Í', 'Icircumflex': 'Î', 'Idieresis': 'Ï',
        'Ograve': 'Ò', 'Oacute': 'Ó', 'Ocircumflex': 'Ô', 'Otilde': 'Õ',
        'Ugrave': 'Ù', 'Uacute': 'Ú', 'Ucircumflex': 'Û',
        'Yacute': 'Ý', 'yacute': 'ý', 'ydieresis': 'ÿ',
        'agrave': 'à', 'aacute': 'á', 'acircumflex': 'â', 'atilde': 'ã',
        'egrave': 'è', 'eacute': 'é', 'ecircumflex': 'ê', 'edieresis': 'ë',
        'igrave': 'ì', 'iacute': 'í', 'icircumflex': 'î', 'idieresis': 'ï',
        'ograve': 'ò', 'oacute': 'ó', 'ocircumflex': 'ô', 'otilde': 'õ',
        'ugrave': 'ù', 'uacute': 'ú', 'ucircumflex': 'û',
        'thorn': 'þ', 'THORN': 'Þ', 'eth': 'ð', 'ETH': 'Ð',
        'ssharp': 'ß', 'mu': 'µ',
        'endash': '–', 'emdash': '—',
        'leftsinglequotemark': "'", 'rightsinglequotemark': "'",
        'leftdoublequotemark': '"', 'rightdoublequotemark': '"',
        'bullet': '•', 'ellipsis': '…',
        'Euro': '€', 'trademark': '™', 'registered': '®', 'copyright': '©',
    }
    if name in standard:
        return standard[name]
    if name.startswith('uni') and len(name) == 7:
        try:
            return chr(int(name[3:], 16))
        except:
            pass
    if name.startswith('u') and len(name) == 5:
        try:
            return chr(int(name[1:], 16))
        except:
            pass
    return ''


def extract_text_from_page(doc: PDFDocument, page: PDFPage) -> str:
    content = doc.get_page_content(page)
    if not content:
        return ""
    parser = ContentStreamParser(doc, page)
    blocks = parser.parse(content)
    page.text_blocks = blocks
    lines = []
    current_line = ""
    last_y = None
    for block in sorted(blocks, key=lambda b: (-b['y'], b['x'])):
        if last_y is not None and abs(block['y'] - last_y) > 5:
            if current_line:
                lines.append(current_line)
                current_line = ""
        current_line += block['text']
        last_y = block['y']
    if current_line:
        lines.append(current_line)
    text = '\n'.join(lines)
    page.text = text
    return text


def extract_all_text(doc: PDFDocument) -> List[str]:
    result = []
    for page in doc.pages:
        result.append(extract_text_from_page(doc, page))
    return result


def check_document(doc: PDFDocument) -> List[Dict]:
    issues = []
    for obj_num, entry in doc.xref_entries.items():
        if not entry.in_use:
            continue
        if entry.is_compressed:
            continue
        if entry.offset >= len(doc.data):
            issues.append({
                'severity': 'high',
                'type': 'xref_offset_invalid',
                'message': f'Object {obj_num}: xref offset {entry.offset} beyond file size {len(doc.data)}'
            })
            continue
        if entry.offset < 0:
            issues.append({
                'severity': 'high',
                'type': 'xref_offset_invalid',
                'message': f'Object {obj_num}: negative xref offset {entry.offset}'
            })
            continue
        try:
            parser = Parser(doc.data[entry.offset:], doc)
            tok1 = parser.peek_token()
            if tok1[0] != 'NUMBER':
                issues.append({
                    'severity': 'medium',
                    'type': 'xref_offset_mismatch',
                    'message': f'Object {obj_num}: xref offset {entry.offset} does not point to object start'
                })
        except:
            pass
    used_refs = set()
    def collect_refs(obj):
        if isinstance(obj, PDFIndirectRef):
            used_refs.add((obj.obj_num, obj.gen_num))
        elif isinstance(obj, PDFDict):
            for v in obj.values():
                collect_refs(v)
        elif isinstance(obj, PDFArray):
            for v in obj:
                collect_refs(v)
        elif isinstance(obj, PDFStream):
            collect_refs(obj.dict)
    for obj in doc.objects.values():
        collect_refs(obj)
    for (ref_num, ref_gen) in used_refs:
        if ref_num not in doc.xref_entries:
            issues.append({
                'severity': 'high',
                'type': 'broken_reference',
                'message': f'Reference to missing object {ref_num} {ref_gen} R'
            })
            continue
        entry = doc.xref_entries[ref_num]
        if not entry.in_use and not entry.is_compressed:
            issues.append({
                'severity': 'medium',
                'type': 'free_object_reference',
                'message': f'Reference to free object {ref_num} {ref_gen} R'
            })
    for (obj_num, gen), obj in doc.objects.items():
        if isinstance(obj, PDFStream):
            actual_len = len(obj.data)
            if '/Length' in obj.dict:
                len_obj = obj.dict['/Length']
                if isinstance(len_obj, PDFIndirectRef):
                    len_obj = doc.resolve(len_obj)
                if isinstance(len_obj, PDFNumber):
                    declared_len = int(len_obj.value)
                    if actual_len != declared_len:
                        issues.append({
                            'severity': 'medium',
                            'type': 'stream_length_mismatch',
                            'message': f'Object {obj_num}: stream declared length {declared_len}, actual {actual_len}'
                        })
    return issues


def obj_to_jsonable(obj):
    if isinstance(obj, PDFNull):
        return None
    if isinstance(obj, PDFBoolean):
        return obj.value
    if isinstance(obj, PDFNumber):
        return obj.value
    if isinstance(obj, PDFName):
        return '/' + obj.name
    if isinstance(obj, PDFString):
        try:
            return obj.value.decode('utf-8')
        except:
            return obj.value.decode('latin-1', errors='replace')
    if isinstance(obj, PDFArray):
        return [obj_to_jsonable(x) for x in obj]
    if isinstance(obj, PDFDict):
        return {k.name: obj_to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, PDFStream):
        return {
            '__type__': 'stream',
            'dict': obj_to_jsonable(obj.dict),
            'data_length': len(obj.data)
        }
    if isinstance(obj, PDFIndirectRef):
        return {'__type__': 'ref', 'obj_num': obj.obj_num, 'gen_num': obj.gen_num}
    return str(obj)


def export_json(doc: PDFDocument) -> Dict:
    extract_all_text(doc)
    result = {
        'header': doc.header,
        'version': doc.version,
        'trailer': obj_to_jsonable(doc.trailer) if doc.trailer else None,
        'objects': {},
        'pages': []
    }
    for (obj_num, gen), obj in doc.objects.items():
        key = f"{obj_num}_{gen}"
        result['objects'][key] = obj_to_jsonable(obj)
    for page in doc.pages:
        pdata = {
            'page_num': page.page_num,
            'ref': {'obj_num': page.ref.obj_num, 'gen_num': page.ref.gen_num} if page.ref else None,
            'mediabox': page.mediabox,
            'cropbox': page.cropbox,
            'resources': obj_to_jsonable(page.resources) if page.resources else None,
            'contents': [{'obj_num': r.obj_num, 'gen_num': r.gen_num} for r in page.contents],
            'text': page.text,
            'text_blocks': page.text_blocks
        }
        result['pages'].append(pdata)
    return result


def search_text(doc: PDFDocument, keyword: str) -> List[Dict]:
    results = []
    all_texts = extract_all_text(doc)
    for i, text in enumerate(all_texts):
        page_num = i + 1
        lines = text.split('\n')
        for j, line in enumerate(lines):
            idx = line.lower().find(keyword.lower())
            if idx >= 0:
                start = max(0, idx - 20)
                end = min(len(line), idx + len(keyword) + 20)
                context = line[start:end]
                if start > 0:
                    context = '...' + context
                if end < len(line):
                    context = context + '...'
                results.append({
                    'page': page_num,
                    'line': j + 1,
                    'column': idx + 1,
                    'context': context
                })
    return results


def extract_images(doc: PDFDocument, output_dir: str) -> List[str]:
    os.makedirs(output_dir, exist_ok=True)
    extracted = []
    images = doc.list_xobjects('Image')
    for i, (ref, stream) in enumerate(images):
        filters = []
        if '/Filter' in stream.dict:
            f = stream.dict['/Filter']
            if isinstance(f, PDFName):
                filters = [f.name]
            elif isinstance(f, PDFArray):
                filters = [x.name for x in f if isinstance(x, PDFName)]
        ext = 'bin'
        data = stream.data
        if 'DCTDecode' in filters:
            ext = 'jpg'
        elif 'FlateDecode' in filters:
            try:
                data = stream.get_filtered_data()
            except:
                pass
        filename = f"image_{ref.obj_num}_{ref.gen_num}.{ext}"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'wb') as f:
            f.write(data)
        extracted.append(filepath)
    return extracted


def print_table(headers: List[str], rows: List[List[str]]):
    cols = [headers] + rows
    widths = [max(len(str(row[i])) for row in cols) for i in range(len(headers))]
    sep = '+' + '+'.join('-' * (w + 2) for w in widths) + '+'
    def fmt_row(r):
        return '|' + '|'.join(' ' + str(r[i]).ljust(widths[i]) + ' ' for i in range(len(r))) + '|'
    print(sep)
    print(fmt_row(headers))
    print(sep)
    for row in rows:
        print(fmt_row(row))
    print(sep)


def cmd_info(doc: PDFDocument):
    print(f"PDF File: {doc.path}")
    print(f"Header: {doc.header}")
    print(f"Version: {doc.version}")
    print(f"File size: {len(doc.data)} bytes")
    print()
    print("=== XRef Statistics ===")
    total = len(doc.xref_entries)
    in_use = sum(1 for e in doc.xref_entries.values() if e.in_use)
    free = total - in_use
    compressed = sum(1 for e in doc.xref_entries.values() if e.is_compressed)
    print_table(['Metric', 'Count'], [
        ['Total xref entries', str(total)],
        ['Objects in use', str(in_use)],
        ['Free objects', str(free)],
        ['Compressed objects', str(compressed)],
        ['Parsed objects', str(len(doc.objects))],
    ])
    print()
    print("=== Trailer ===")
    if doc.trailer:
        for k, v in doc.trailer.items():
            print(f"  {k}: {v}")
    print()
    print("=== Pages ===")
    extract_all_text(doc)
    page_rows = []
    for page in doc.pages:
        mb = f"{page.mediabox}" if page.mediabox else "N/A"
        cb = f"{page.cropbox}" if page.cropbox else "N/A"
        nc = len(page.contents)
        nt = len(page.text_blocks)
        page_rows.append([str(page.page_num), mb, cb, str(nc), str(nt)])
    print_table(['#', 'MediaBox', 'CropBox', 'Streams', 'Text Blocks'], page_rows)
    print()
    print("=== Font Objects ===")
    fonts = doc.list_all_objects_by_type('Font')
    font_rows = []
    for ref, obj in fonts:
        subtype = ''
        if isinstance(obj, PDFDict) and '/Subtype' in obj:
            st = obj['/Subtype']
            if isinstance(st, PDFName):
                subtype = st.name
        basefont = ''
        if isinstance(obj, PDFDict) and '/BaseFont' in obj:
            bf = obj['/BaseFont']
            if isinstance(bf, PDFName):
                basefont = bf.name
        font_rows.append([f"{ref.obj_num} {ref.gen_num} R", subtype, basefont])
    if font_rows:
        print_table(['Ref', 'Subtype', 'BaseFont'], font_rows)
    else:
        print("  (none)")
    print()
    print("=== Image XObjects ===")
    images = doc.list_xobjects('Image')
    img_rows = []
    for ref, stream in images:
        w = ''
        h = ''
        if '/Width' in stream.dict:
            w = str(stream.dict['/Width'].value)
        if '/Height' in stream.dict:
            h = str(stream.dict['/Height'].value)
        cs = ''
        if '/ColorSpace' in stream.dict:
            cs_obj = stream.dict['/ColorSpace']
            if isinstance(cs_obj, PDFName):
                cs = cs_obj.name
            else:
                cs = str(cs_obj)[:30]
        img_rows.append([f"{ref.obj_num} {ref.gen_num} R", w, h, cs, str(len(stream.data))])
    if img_rows:
        print_table(['Ref', 'Width', 'Height', 'ColorSpace', 'Size'], img_rows)
    else:
        print("  (none)")
    print()
    print("=== Metadata Objects ===")
    metas = doc.list_all_objects_by_type('Metadata')
    if metas:
        for ref, obj in metas:
            print(f"  {ref.obj_num} {ref.gen_num} R")
    else:
        print("  (none)")


def cmd_text(doc: PDFDocument, output_path: str = None):
    all_texts = extract_all_text(doc)
    lines = []
    for i, text in enumerate(all_texts):
        lines.append(f"# Page {i + 1}")
        lines.append("")
        lines.append(text)
        lines.append("")
    md_content = '\n'.join(lines)
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        print(f"Text extracted to {output_path}")
    else:
        print(md_content)


def cmd_search(doc: PDFDocument, keyword: str):
    results = search_text(doc, keyword)
    if not results:
        print(f"No matches found for '{keyword}'")
        return
    print(f"Found {len(results)} match(es) for '{keyword}':")
    print()
    rows = []
    for r in results:
        rows.append([str(r['page']), str(r['line']), str(r['column']), r['context']])
    print_table(['Page', 'Line', 'Col', 'Context'], rows)


def cmd_check(doc: PDFDocument):
    issues = check_document(doc)
    if not issues:
        print("No issues detected.")
        return
    high = sum(1 for i in issues if i['severity'] == 'high')
    medium = sum(1 for i in issues if i['severity'] == 'medium')
    low = sum(1 for i in issues if i['severity'] == 'low')
    print(f"Issues found: {len(issues)} (high: {high}, medium: {medium}, low: {low})")
    print()
    rows = []
    for i in issues:
        sev = i['severity'].upper()
        rows.append([sev, i['type'], i['message']])
    print_table(['Severity', 'Type', 'Message'], rows)


def cmd_export_json(doc: PDFDocument, output_path: str):
    data = export_json(doc)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"JSON exported to {output_path}")


def cmd_extract_images(doc: PDFDocument, output_dir: str):
    extracted = extract_images(doc, output_dir)
    if not extracted:
        print("No images found.")
        return
    print(f"Extracted {len(extracted)} image(s) to {output_dir}:")
    for p in extracted:
        print(f"  {p}")


def cmd_report(doc: PDFDocument, output_path: str):
    issues = check_document(doc)
    extract_all_text(doc)
    fonts = doc.list_all_objects_by_type('Font')
    images = doc.list_xobjects('Image')
    metas = doc.list_all_objects_by_type('Metadata')
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>PDF Inspection Report - {os.path.basename(doc.path)}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 40px; background: #f8f9fa; color: #333; }}
h1 {{ color: #1a1a1a; border-bottom: 3px solid #4a90d9; padding-bottom: 10px; }}
h2 {{ color: #2c5282; margin-top: 30px; border-left: 4px solid #4a90d9; padding-left: 10px; }}
h3 {{ color: #4a5568; }}
table {{ border-collapse: collapse; margin: 15px 0; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
th, td {{ border: 1px solid #ddd; padding: 10px 15px; text-align: left; }}
th {{ background: #4a90d9; color: white; }}
tr:nth-child(even) {{ background: #f7fafc; }}
.high {{ background: #fed7d7 !important; color: #c53030; }}
.medium {{ background: #fefcbf !important; color: #d69e2e; }}
.low {{ background: #c6f6d5 !important; color: #276749; }}
.stats {{ display: flex; gap: 20px; flex-wrap: wrap; }}
.stat-card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); min-width: 150px; }}
.stat-card .num {{ font-size: 28px; font-weight: bold; color: #4a90d9; }}
.stat-card .label {{ font-size: 12px; color: #718096; text-transform: uppercase; }}
pre {{ background: #2d3748; color: #e2e8f0; padding: 15px; border-radius: 6px; overflow-x: auto; }}
code {{ background: #edf2f7; padding: 2px 6px; border-radius: 3px; }}
</style>
</head>
<body>
<h1>PDF Inspection Report</h1>
<p><strong>File:</strong> <code>{os.path.basename(doc.path)}</code></p>

<h2>Overview</h2>
<div class="stats">
  <div class="stat-card"><div class="num">{doc.version}</div><div class="label">PDF Version</div></div>
  <div class="stat-card"><div class="num">{len(doc.pages)}</div><div class="label">Pages</div></div>
  <div class="stat-card"><div class="num">{len(doc.objects)}</div><div class="label">Objects</div></div>
  <div class="stat-card"><div class="num">{len(fonts)}</div><div class="label">Fonts</div></div>
  <div class="stat-card"><div class="num">{len(images)}</div><div class="label">Images</div></div>
  <div class="stat-card"><div class="num">{len(issues)}</div><div class="label">Issues</div></div>
</div>

<h2>Pages</h2>
<table>
<tr><th>#</th><th>MediaBox</th><th>CropBox</th><th>Content Streams</th><th>Text Blocks</th></tr>
"""
    for page in doc.pages:
        html += f"<tr><td>{page.page_num}</td><td>{page.mediabox}</td><td>{page.cropbox or 'N/A'}</td><td>{len(page.contents)}</td><td>{len(page.text_blocks)}</td></tr>\n"
    html += """</table>

<h2>Object Tree</h2>
<h3>Pages</h3>
<ul>
"""
    for page in doc.pages:
        ref_str = f"{page.ref.obj_num} {page.ref.gen_num} R" if page.ref else "N/A"
        html += f"<li>Page {page.page_num}: <code>{ref_str}</code></li>\n"
    html += "</ul>"
    if fonts:
        html += "<h3>Fonts</h3><ul>"
        for ref, obj in fonts:
            html += f"<li><code>{ref.obj_num} {ref.gen_num} R</code></li>\n"
        html += "</ul>"
    if images:
        html += "<h3>Images</h3><ul>"
        for ref, obj in images:
            w = h = "?"
            if '/Width' in obj.dict:
                w = str(obj.dict['/Width'].value)
            if '/Height' in obj.dict:
                h = str(obj.dict['/Height'].value)
            html += f"<li><code>{ref.obj_num} {ref.gen_num} R</code> ({w}x{h})</li>\n"
        html += "</ul>"
    if metas:
        html += "<h3>Metadata</h3><ul>"
        for ref, obj in metas:
            html += f"<li><code>{ref.obj_num} {ref.gen_num} R</code></li>\n"
        html += "</ul>"
    html += """
<h2>Extracted Text</h2>
"""
    for i, page in enumerate(doc.pages):
        html += f"<h3>Page {page.page_num}</h3>\n<pre>{page.text}</pre>\n"
    if issues:
        html += """<h2>Issues</h2><table><tr><th>Severity</th><th>Type</th><th>Message</th></tr>"""
        for issue in issues:
            html += f"<tr class=\"{issue['severity']}\"><td>{issue['severity'].upper()}</td><td>{issue['type']}</td><td>{issue['message']}</td></tr>\n"
        html += "</table>"
    else:
        html += "<h2>Issues</h2><p>No issues detected.</p>"
    html += "</body></html>"
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"HTML report generated: {output_path}")


def main():
    parser = argparse.ArgumentParser(description='PDF Structure Inspector and Text Extractor')
    subparsers = parser.add_subparsers(dest='command', required=True)
    p_info = subparsers.add_parser('info', help='Show PDF structure info')
    p_info.add_argument('file', help='PDF file path')
    p_text = subparsers.add_parser('text', help='Extract text to Markdown')
    p_text.add_argument('file', help='PDF file path')
    p_text.add_argument('-o', '--output', help='Output Markdown file')
    p_search = subparsers.add_parser('search', help='Search text in PDF')
    p_search.add_argument('file', help='PDF file path')
    p_search.add_argument('keyword', help='Search keyword')
    p_check = subparsers.add_parser('check', help='Check PDF for issues')
    p_check.add_argument('file', help='PDF file path')
    p_report = subparsers.add_parser('report', help='Generate HTML report')
    p_report.add_argument('file', help='PDF file path')
    p_report.add_argument('-o', '--output', required=True, help='Output HTML file')
    p_json = subparsers.add_parser('export-json', help='Export structured JSON')
    p_json.add_argument('file', help='PDF file path')
    p_json.add_argument('-o', '--output', required=True, help='Output JSON file')
    p_img = subparsers.add_parser('extract-images', help='Extract images')
    p_img.add_argument('file', help='PDF file path')
    p_img.add_argument('-o', '--output', required=True, help='Output directory')
    args = parser.parse_args()
    if not os.path.exists(args.file):
        print(f"Error: file not found: {args.file}", file=sys.stderr)
        sys.exit(1)
    try:
        doc = PDFDocument(args.file)
    except Exception as e:
        print(f"Error parsing PDF: {e}", file=sys.stderr)
        sys.exit(1)
    if args.command == 'info':
        cmd_info(doc)
    elif args.command == 'text':
        cmd_text(doc, args.output)
    elif args.command == 'search':
        cmd_search(doc, args.keyword)
    elif args.command == 'check':
        cmd_check(doc)
    elif args.command == 'report':
        cmd_report(doc, args.output)
    elif args.command == 'export-json':
        cmd_export_json(doc, args.output)
    elif args.command == 'extract-images':
        cmd_extract_images(doc, args.output)


if __name__ == '__main__':
    main()
