#!/usr/bin/env python3
"""Parchea Gangstar: Miami Vindication v1.0.6 (mod NamAnhVN) para Android moderno.

Uso: python3 patch_gangstar.py orig.apk salida.apk [keystore] [alias] [pass]

1. NOP del sprintf("%f", int) en Preferences::LoadAndApply (libGangster2.so, 0x2c059c)
2. Mueve META-INF/MYAPP.RSA original a META-INF/o/MYAPP.RSA (lo lee libStormGLOFT.so)
3. zipalign + apksigner solo con esquema v2
"""
import os
import subprocess
import sys
import zipfile

SO = "lib/armeabi/libGangster2.so"
OFF = 0x2C059C
ORIG = bytes.fromhex("b4f7fae9")  # blx sprintf
NOP = bytes.fromhex("00bf00bf")   # nop; nop
DROP = ("META-INF/MANIFEST.MF", "META-INF/MYAPP.SF")


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    ks = sys.argv[3] if len(sys.argv) > 3 else "debug.jks"
    alias = sys.argv[4] if len(sys.argv) > 4 else "k"
    pw = sys.argv[5] if len(sys.argv) > 5 else "android"
    tmp, aligned = dst + ".tmp.apk", dst + ".aligned.apk"

    zin = zipfile.ZipFile(src)
    if "META-INF/MYAPP.RSA" not in zin.namelist():
        sys.exit("No encuentro META-INF/MYAPP.RSA: este no es el APK original del mod.")

    with zipfile.ZipFile(tmp, "w") as zout:
        for i in zin.infolist():
            name, data = i.filename, zin.read(i.filename)
            if name in DROP:
                continue
            if name == "META-INF/MYAPP.RSA":
                name = "META-INF/o/MYAPP.RSA"
            if name == SO:
                if data[OFF:OFF + 4] != ORIG:
                    sys.exit("Bytes inesperados en 0x2c059c: version distinta del mod.")
                data = data[:OFF] + NOP + data[OFF + 4:]
                print("sprintf anulado en", SO)
            z = zipfile.ZipInfo(name, i.date_time)
            z.compress_type = i.compress_type
            z.external_attr = i.external_attr
            zout.writestr(z, data)

    subprocess.run(["zipalign", "-f", "-p", "4", tmp, aligned], check=True)
    subprocess.run([
        "apksigner", "sign", "--ks", ks, "--ks-pass", "pass:" + pw, "--ks-key-alias", alias,
        "--min-sdk-version", "24",
        "--v1-signing-enabled", "false", "--v2-signing-enabled", "true",
        "--v3-signing-enabled", "false", "--v4-signing-enabled", "false",
        "--out", dst, aligned,
    ], check=True)
    for f in (tmp, aligned, dst + ".idsig", aligned + ".idsig"):
        if os.path.exists(f):
            os.remove(f)
    print("Listo:", dst)


if __name__ == "__main__":
    main()
