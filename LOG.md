# Log de investigación

Dispositivo: Samsung Galaxy A34 5G, Android 16 (arm64 con soporte 32-bit).
Juego: Gangstar: Miami Vindication v1.0.6 "Fix" de David Rice (gameloftrepairgames / Gameloft Repair Games), paquete `com.gameloft.android.GAND.GloftGMHP.ML`, `targetSdk=5`, ABI `armeabi` (Thumb).
Herramientas: adb (inalámbrico), apktool, apksigner, zipalign, radare2, llvm-objdump, readelf, python3.

## Fase 1: reproducir y localizar el crash

- El juego abre bien la primera vez. Tras jugar y reabrir, se cierra justo después del logo de Gameloft.
- El save/preferencias están en la memoria interna de la app, no en `/sdcard`.
- Crash capturado con `adb logcat -b crash`:

```
Abort message: 'stack corruption detected (-fstack-protector)'
libGangster2.so (Preferences::LoadAndApply(char const*)+734)   [hilo GLThread]
```

- Solo ocurre cuando el archivo de preferencias ya existe. `monkey` no genera gameplay real, hay que jugar a mano.
- Con APK **re-firmado** aparecía además otro cierre tras el logo que se tomó por un segundo crash (`libStormGLOFT.so`, `JNI_OnLoad`). Más adelante resultó ser otra cosa (fase 5).

## Fase 2: análisis estático de `LoadAndApply` (radare2)

- Función en `0x2c0388`, frame de 1620 bytes, despacha por tabla de salto sobre bloques `Persistence::Block*`.
- Se revisaron una a una las ramas (`setThrottleMode`, `setSteeringMode`, `setPlaylist`, `SetOrientation`, volúmenes, etc.) y los `Read()` de `BlockString`, `BlockInt`, `BlockIntPair`: todos limpios.
- Se encontró un `memset(buf, 0, 96)` + `sprintf(buf, "%f", ...)` en `0x2c0592`/`0x2c059c`. Se resolvió el formato vía aritmética sobre la GOT (`0x6349d8 - 0xb2180 = 0x582858`) y era `"%f"`. Se **descartó por error**: se asumió que el argumento era un float normal.

## Fase 3: parches de diagnóstico (callejón sin salida)

| Parche | Offset | Resultado |
|---|---|---|
| Anular el chequeo del canario en `LoadAndApply` (`beq` -> `b`) | `0x2c03da` | No arregla nada |
| Anular el instalador del hook `nativeExit` de storm | `0x3246e` | Evita una salida pero deja **pantalla negra** (audio y táctil funcionan) |

- Se crearon variantes de APK con `mk3.py` (`ctrl`, `patch`, `nostorm`, `nocanary`, `bothpatch`, `allpatch`).

## Fase 4: la pista decisiva del crash

Con canario y storm parcheados, `Gangstar2.preferences` se creó (248 bytes, en la raíz de la app) y al reabrir:

```
signal 7 (SIGBUS), fault addr 0x34353232
r2 31323132  r3 30353232  r4 35373832 ...   <- todo dígitos ASCII
pc 34353232
```

Los registros llenos de dígitos decimales significaban que **un número enorme impreso como texto había pisado todo el frame**. Eso apuntó de vuelta al `sprintf("%f", int)`: en la ABI ARM el `%f` lee un `double` de `r2:r3`; `r2` es el entero y `r3` es basura, lo que genera un número de cientos de dígitos que revienta el buffer de 96 bytes.

- Parche: NOP (`00bf00bf`) en `0x2c059c`, restaurando el canario original.
- Confirmado con `fix1` (storm aún parcheado): reabre con el archivo de preferencias existente sin crashear.

## Fase 5: por qué el APK re-firmado se cierra tras el logo

Se probó `fix2` (solo el NOP, storm intacto, re-firmado). Aclaración de un error de la sesión: el "fix2" que primero se probó era en realidad `fix1` (storm parcheado, de ahí la pantalla negra); `fix2-signed.apk` no existía aún.

Con `fix2` real, el juego se cierra tras el logo. El log mostró:

```
GameLoft: Width-of-the-Screen :2009
Gangstar2: Native Exit Triggered
System.out: ----- EXIT APP -----
ND.GloftGMHP.ML: System.exit called, status: 0
```

No es un crash: es una salida voluntaria dentro de `Application::Init`. En `orig.apk` (firma original) esa línea no aparece y sigue `App Init Successful`.

### Hipótesis probadas y descartadas

| Hipótesis | Prueba | Resultado |
|---|---|---|
| Depende de `debuggable` | `fix4` (debuggable + storm intacto) | Sale igual |
| Instalación incremental (`.idsig`) | `--no-incremental` | Sale igual |
| Solo firma v1 en vez de v2/v3 | firma v1 | Sale igual |
| Nombre del firmante v1 | `--v1-signer-name MYAPP` | Sale igual |
| Reescritura del zip / `zipalign` | `orig.apk` solo re-firmado, sin tocar el zip | Sale igual |
| Flag que lee `nativeExit` (`0x368908`) | NOP del `bne` en `0x368916` | Sale igual (hay otros llamadores) |
| Play Protect | Dispara solo con el original, pero no influye | Irrelevante |

### Pista que resolvió el problema

`strings` sobre `libStormGLOFT.so` mostró minizip (`unzGetGlobalInfo`) y la cadena `META-INF/`. Desensamblando `fcn.000365b0` y `0x36950` se vio que storm abre el APK como zip, filtra entradas `META-INF/*.RSA` (`.RSA`/`.DSA`/`.EC`) y las lee. Hipótesis: storm necesita el certificado original dentro del zip.

Prueba (`t3`): quitar `MANIFEST.MF` y `MYAPP.SF`, mover `MYAPP.RSA` original a `META-INF/o/MYAPP.RSA` y firmar solo con v2 (`apksigner` con `--min-sdk-version 24`, porque el `minSdk` bajo del manifest hacía que exigiera v1 al verificar).

**Resultado: el juego arranca con imagen, sin crash, y la partida se guarda y se reabre.**

## Estado final

- Parche 1 (bug de preferencias): NOP en `0x2c059c` de `libGangster2.so`.
- Parche 2 (arranque con APK re-firmado): `MYAPP.RSA` original dentro de `META-INF/o/` + firma solo v2.
- No se tocó storm ni el canario.

## Pendiente / sin aclarar

- Qué hace storm exactamente con el `.RSA` (comparación, hash, otra cosa): solo se sabe que lo lee y que con él presente el juego arranca.
- El `sprintf` de la rama del volumen de efectos no se parchó: solo se anuló el de la música, que era el que se ejecutaba. Falta confirmar si hay otro `sprintf` equivalente.
- Fuera de Android 16 / Galaxy A34 no se probó.
