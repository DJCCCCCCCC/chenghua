from pathlib import Path
from PyInstaller.archive.readers import CArchiveReader
archive = r'D:\桌面\Code\绘图工具逆向\YouYu自动绘画.exe'
out = Path(r'D:\桌面\Code\绘图工具逆向\analysis_extract')
reader = CArchiveReader(archive)
for name in ['modern_main', 'siliconflow_generator', 'space_gradio_client', 'tag_translate', 'update_downloader', 'theme', 'version_info', '1763310716369.jpg', 'IMG_4639.png', '画猜彩绘预览.gif', 'wx收款.png']:
    item = reader.toc.find(name)
    if item == -1:
        print('missing', name)
        continue
    typ, data = reader.extract(name)
    safe = name.replace('\\', '_').replace('/', '_')
    path = out / safe
    path.write_bytes(data)
    print(name, 'type=', typ, 'bytes=', len(data), 'head=', data[:16].hex())
