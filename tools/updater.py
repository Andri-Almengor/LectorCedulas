import argparse
import os
import shutil

PRESERVE = {'licencia.key'}
PRESERVE_DIRS = {'configs'}

def copy_tree(src, dst):
    os.makedirs(dst, exist_ok=True)
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target_root = dst if rel == '.' else os.path.join(dst, rel)
        os.makedirs(target_root, exist_ok=True)
        for fn in files:
            if rel == '.' and fn in PRESERVE:
                continue
            if rel.split(os.sep)[0] in PRESERVE_DIRS:
                continue
            shutil.copy2(os.path.join(root, fn), os.path.join(target_root, fn))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--target', required=True)
    args = parser.parse_args()
    copy_tree(args.source, args.target)
    print('Update aplicado correctamente.')
