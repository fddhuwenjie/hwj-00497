#!/usr/bin/env python3
import os
import zlib


def build_pdf(objects_list):
    output = bytearray()
    output.extend(b'%PDF-1.4\n')
    output.extend(b'%\\xe2\\xe3\\xcf\\xd3\n')
    offsets = []
    for obj in objects_list:
        offsets.append(len(output))
        output.extend(obj.encode('latin-1'))
        output.extend(b'\n')
    xref_offset = len(output)
    output.extend(f'xref\n0 {len(objects_list) + 1}\n'.encode('latin-1'))
    output.extend(b'0000000000 65535 f \n')
    for off in offsets:
        output.extend(f'{off:010d} 00000 n \n'.encode('latin-1'))
    output.extend(f'trailer\n<< /Size {len(objects_list) + 1} /Root 1 0 R >>\n'.encode('latin-1'))
    output.extend(f'startxref\n{xref_offset}\n%%EOF\n'.encode('latin-1'))
    return bytes(output)


def make_sample1():
    content = """BT
/F1 24 Tf
100 700 Td
(Hello, World!) Tj
0 -40 Td
/F2 14 Tf
(This is a simple single-page PDF.) Tj
0 -20 Td
(Pure text, no compression, standard fonts.) Tj
ET
"""
    objects = [
        '1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj',
        '2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj',
        '3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>\nendobj',
        '4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj',
        '5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman >>\nendobj',
        f'6 0 obj\n<< /Length {len(content)} >>\nstream\n{content}endstream\nendobj',
    ]
    return build_pdf(objects)


def make_sample2():
    page1_content = """BT
/F1 20 Tf
72 720 Td
(Page 1: Multi-page PDF Test) Tj
0 -30 Td
/F2 12 Tf
(This PDF contains multiple pages with different fonts.) Tj
0 -20 Td
(Testing font encoding and text extraction.) Tj
ET
"""
    page2_content = "BT\n" \
        "/F1 18 Tf\n" \
        "72 720 Td\n" \
        "(Page 2: Continued Content) Tj\n" \
        "0 -30 Td\n" \
        "/F3 12 Tf\n" \
        "(Using WinAnsiEncoding: ) Tj\n" \
        "[(Special) 120 (chars) 120 (test)] TJ\n" \
        "0 -20 Td\n" \
        "(Umlauts: \\204\\201\\202\\203\\205) Tj\n" \
        "0 -20 Td\n" \
        "(German: \\304\\326\\334 \\344\\366\\374 \\337) Tj\n" \
        "ET\n"
    page3_content = """BT
/F2 16 Tf
72 720 Td
(Page 3: Final Page) Tj
0 -25 Td
/F1 11 Tf
(End of multi-page document. The quick brown fox) Tj
0 -15 Td
(jumps over the lazy dog. 0123456789 !@#$%^&*()) Tj
ET
"""
    objects = [
        '1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj',
        '2 0 obj\n<< /Type /Pages /Kids [3 0 R 6 0 R 9 0 R] /Count 3 >>\nendobj',
        '3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 11 0 R /F2 12 0 R >> >> /Contents 4 0 R >>\nendobj',
        f'4 0 obj\n<< /Length {len(page1_content)} >>\nstream\n{page1_content}endstream\nendobj',
        '5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj',
        '6 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 11 0 R /F3 13 0 R >> >> /Contents 7 0 R >>\nendobj',
        f'7 0 obj\n<< /Length {len(page2_content)} >>\nstream\n{page2_content}endstream\nendobj',
        '8 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman >>\nendobj',
        '9 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 11 0 R /F2 12 0 R >> >> /Contents 10 0 R >>\nendobj',
        f'10 0 obj\n<< /Length {len(page3_content)} >>\nstream\n{page3_content}endstream\nendobj',
        '11 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj',
        '12 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman >>\nendobj',
        '13 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>\nendobj',
    ]
    return build_pdf(objects)


def make_sample3():
    text_content = """BT
/F1 18 Tf
72 720 Td
(PDF with Image and Compressed Stream) Tj
0 -30 Td
/F2 12 Tf
(This page contains FlateDecode compressed content) Tj
0 -20 Td
(and a DCTDecode JPEG image XObject.) Tj
0 -40 Td
(Image below:) Tj
ET
"""
    compressed_text = zlib.compress(text_content.encode('latin-1'))
    small_jpeg = bytes.fromhex(
        'ffd8ffe000104a46494600010100000100010000ffdb00430008060607060508070707'
        '0909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c28'
        '37292c30313434341f27393d38323c2e333432ffdb0043010909090c0b0c180d0d1832'
        '211c213232323232323232323232323232323232323232323232323232323232323232'
        '323232323232323232323232323232323232323232ffc0001108000100010301220002'
        '1101031101ffc4001f0000010501010101010100000000000000000102030405060708'
        '090a0bffc400b5100002010303020403050504040000017d0102030004110512213141'
        '0613516107227114328191a1082342b1c11552d1f02433627282090a161718191a2526'
        '2728292a3435363738393a434445464748494a535455565758595a63646566676869'
        '6a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9'
        'aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5'
        'e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffc4001f010003010101010101010101000000'
        '0000000102030405060708090a0bffc400b511000201020404030407050404000102'
        '77000102031104052131061241510761711322328108144291a1b1c109233352f015'
        '6272d10a162434e125f11718191a262728292a35363738393a434445464748494a53'
        '5455565758595a636465666768696a737475767778797a82838485868788898a9293'
        '9495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9ca'
        'd2d3d4d5d6d7d8d9dae2e3e4e5e6e7e8e9eaf2f3f4f5f6f7f8f9faffda000c030100'
        '02110311003f00fbd0a28a2800ffd9'
    )
    objects = [
        '1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj',
        '2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj',
        '3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 7 0 R /F2 8 0 R >> /XObject << /Im1 5 0 R >> >> /Contents 4 0 R >>\nendobj',
        f'4 0 obj\n<< /Length {len(compressed_text)} /Filter /FlateDecode >>\nstream\n',
        f'5 0 obj\n<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {len(small_jpeg)} >>\nstream\n',
        '7 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>\nendobj',
        '8 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>\nendobj',
    ]
    output = bytearray()
    output.extend(b'%PDF-1.4\n')
    output.extend(b'%\\xe2\\xe3\\xcf\\xd3\n')
    offsets = []
    for i, obj in enumerate(objects):
        offsets.append(len(output))
        if i == 4:
            output.extend(obj.encode('latin-1'))
            output.extend(small_jpeg)
            output.extend(b'\nendstream\nendobj\n')
        elif i == 3:
            output.extend(obj.encode('latin-1'))
            output.extend(compressed_text)
            output.extend(b'\nendstream\nendobj\n')
        else:
            output.extend(obj.encode('latin-1'))
            output.extend(b'\n')
    xref_offset = len(output)
    output.extend(f'xref\n0 {len(objects) + 1}\n'.encode('latin-1'))
    output.extend(b'0000000000 65535 f \n')
    for off in offsets:
        output.extend(f'{off:010d} 00000 n \n'.encode('latin-1'))
    output.extend(f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n'.encode('latin-1'))
    output.extend(f'startxref\n{xref_offset}\n%%EOF\n'.encode('latin-1'))
    return bytes(output)


def make_sample4_objstream():
    page_content = """BT
/F1 18 Tf
72 720 Td
(Object Stream and XRef Stream Test) Tj
0 -30 Td
/F2 12 Tf
(This PDF uses compressed object streams) Tj
0 -20 Td
(and a cross-reference stream instead of xref table.) Tj
0 -20 Td
(Objects like Fonts and Page content are stored inside) Tj
0 -20 Td
(the /ObjStm stream and resolved via xref stream type 2.) Tj
ET
"""
    compressed_page = zlib.compress(page_content.encode('latin-1'))
    inner_objs = [
        '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>',
        '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
    ]
    obj_stm_header = ""
    offset = 0
    inner_objects_data = []
    for i, inner in enumerate(inner_objs):
        obj_num = 4 + i
        obj_stm_header += f"{obj_num} {offset} "
        inner_bytes = inner.encode('latin-1')
        inner_objects_data.append(inner_bytes)
        offset += len(inner_bytes) + 1
    obj_stm_body = obj_stm_header.strip() + "\n" + "\n".join(x.decode('latin-1') for x in inner_objects_data) + "\n"
    first_offset = len(obj_stm_header.strip()) + 1
    compressed_objstm = zlib.compress(obj_stm_body.encode('latin-1'))
    output = bytearray()
    output.extend(b'%PDF-1.5\n')
    output.extend(b'%\xe2\xe3\xcf\xd3\n')
    offsets = {}
    objects_to_write = []
    obj1 = b'1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n'
    obj2 = b'2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n'
    obj3 = (f'3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
            f'/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>\nendobj\n').encode('latin-1')
    obj6_header = f'6 0 obj\n<< /Length {len(compressed_page)} /Filter /FlateDecode >>\nstream\n'.encode('latin-1')
    obj6_footer = b'\nendstream\nendobj\n'
    obj7_header = (f'7 0 obj\n<< /Type /ObjStm /N {len(inner_objs)} /First {first_offset} '
                   f'/Length {len(compressed_objstm)} /Filter /FlateDecode >>\nstream\n').encode('latin-1')
    obj7_footer = b'\nendstream\nendobj\n'
    all_parts = [
        (1, obj1),
        (2, obj2),
        (3, obj3),
        (6, obj6_header + compressed_page + obj6_footer),
        (7, obj7_header + compressed_objstm + obj7_footer),
    ]
    for num, data in all_parts:
        offsets[num] = len(output)
        output.extend(data)
    xref_stream_offset = len(output)
    xref_entries_bytes = bytearray()
    max_obj = max(max(offsets.keys()), 5)
    for obj_num in range(max_obj + 1):
        if obj_num == 0:
            entry = bytes([0, 0, 0, 0, 0, 65535 >> 8, 65535 & 0xFF])
            xref_entries_bytes.extend(bytes([0, 0, 0, 0, 0, 0xFF, 0xFF]))
        elif obj_num in offsets:
            off = offsets[obj_num]
            entry = bytes([1]) + off.to_bytes(4, 'big') + (0).to_bytes(2, 'big')
            xref_entries_bytes.extend(entry)
        elif obj_num in (4, 5):
            idx_in_stm = obj_num - 4
            entry = bytes([2]) + (7).to_bytes(4, 'big') + idx_in_stm.to_bytes(2, 'big')
            xref_entries_bytes.extend(entry)
        else:
            xref_entries_bytes.extend(bytes([0, 0, 0, 0, 0, 0xFF, 0xFF]))
    xref_size = max_obj + 1
    xref_dict = (f'<< /Type /XRef /Size {xref_size} /W [1 4 2] /Root 1 0 R '
                 f'/Length {len(xref_entries_bytes)} >>').encode('latin-1')
    xref_obj_header = f'8 0 obj\n'.encode('latin-1')
    xref_stream_obj = xref_obj_header + xref_dict + b'\nstream\n' + bytes(xref_entries_bytes) + b'\nendstream\nendobj\n'
    output.extend(xref_stream_obj)
    startxref_data = f'startxref\n{xref_stream_offset}\n%%EOF\n'.encode('latin-1')
    output.extend(startxref_data)
    return bytes(output)


def make_sample5_tounicode():
    cmap_content = """/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
/CIDSystemInfo
<< /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def
/CMapName /Adobe-Identity-UCS def
/CMapType 2 def
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
3 beginbfchar
<0001> <4E2D>
<0002> <6587>
<0003> <6D4B>
endbfchar
2 beginbfrange
<0010> <0012> <8BD5>
<0020> <0021> [<0041> <0042>]
endbfrange
endcmap
CMapName currentdict /CMap defineresource pop
end
end
"""
    compressed_cmap = zlib.compress(cmap_content.encode('latin-1'))
    hex_text = "00010002000300100011001200200021"
    page_content = f"""BT
/F1 20 Tf
72 720 Td
<{hex_text}> Tj
0 -40 Td
/F2 12 Tf
(ToUnicode CMap with Chinese characters test) Tj
0 -20 Td
(bfchar, bfrange, and array forms all covered.) Tj
ET
"""
    compressed_page = zlib.compress(page_content.encode('latin-1'))
    output = bytearray()
    output.extend(b'%PDF-1.4\n')
    output.extend(b'%\xe2\xe3\xcf\xd3\n')
    offsets = []
    objects = [
        '1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj',
        '2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj',
        '3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R /F2 6 0 R >> >> /Contents 7 0 R >>\nendobj',
        '4 0 obj\n<< /Type /Font /Subtype /Type0 /BaseFont /SimSun /Encoding /Identity-H /DescendantFonts [5 0 R] /ToUnicode 8 0 R >>\nendobj',
        '5 0 obj\n<< /Type /Font /Subtype /CIDFontType2 /BaseFont /SimSun /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> /W [ ] >>\nendobj',
        '6 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj',
        None,
        None,
    ]
    for i, obj in enumerate(objects):
        obj_num = i + 1
        offsets.append(len(output))
        if obj_num == 7:
            header = f'7 0 obj\n<< /Length {len(compressed_page)} /Filter /FlateDecode >>\nstream\n'
            output.extend(header.encode('latin-1'))
            output.extend(compressed_page)
            output.extend(b'\nendstream\nendobj\n')
        elif obj_num == 8:
            header = f'8 0 obj\n<< /Length {len(compressed_cmap)} /Filter /FlateDecode >>\nstream\n'
            output.extend(header.encode('latin-1'))
            output.extend(compressed_cmap)
            output.extend(b'\nendstream\nendobj\n')
        else:
            output.extend(obj.encode('latin-1'))
            output.extend(b'\n')
    xref_offset = len(output)
    output.extend(f'xref\n0 {len(objects) + 1}\n'.encode('latin-1'))
    output.extend(b'0000000000 65535 f \n')
    for off in offsets:
        output.extend(f'{off:010d} 00000 n \n'.encode('latin-1'))
    output.extend(f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n'.encode('latin-1'))
    output.extend(f'startxref\n{xref_offset}\n%%EOF\n'.encode('latin-1'))
    return bytes(output)


def main():
    samples_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'samples')
    os.makedirs(samples_dir, exist_ok=True)
    with open(os.path.join(samples_dir, 'sample1_text.pdf'), 'wb') as f:
        f.write(make_sample1())
    print("Created samples/sample1_text.pdf")
    with open(os.path.join(samples_dir, 'sample2_multipage.pdf'), 'wb') as f:
        f.write(make_sample2())
    print("Created samples/sample2_multipage.pdf")
    with open(os.path.join(samples_dir, 'sample3_image.pdf'), 'wb') as f:
        f.write(make_sample3())
    print("Created samples/sample3_image.pdf")
    with open(os.path.join(samples_dir, 'sample4_objstream.pdf'), 'wb') as f:
        f.write(make_sample4_objstream())
    print("Created samples/sample4_objstream.pdf")
    with open(os.path.join(samples_dir, 'sample5_tounicode.pdf'), 'wb') as f:
        f.write(make_sample5_tounicode())
    print("Created samples/sample5_tounicode.pdf")


if __name__ == '__main__':
    main()
