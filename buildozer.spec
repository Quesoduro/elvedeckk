[app]
# (str) Title of your application
title = Adopt Me In Time

# (str) Package name
package.name = miapp

# (str) Package domain (needed for android/ios packaging)
package.domain = org.ejemplo

# (str) Source code where the main.py lives
source.dir = .

# (list) Source files to include (python files, images, etc.)
source.include_exts = py,png,jpg,kv,atlas

# (str) Application versioning
version = 0.1

# (list) Application requirements
# Fijamos la versión estable de Python a 3.10 para evitar errores de Cython
requirements = python3==3.10.12,kivy==2.3.0

# (str) Supported orientation (one of landscape, sensorLandscape, portrait or all)
orientation = portrait

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (list) Permissions
# android.permissions = INTERNET

# (list) Target architectures
# Solo arm64-v8a para reducir el tiempo de compilación a la mitad
android.archs = arm64-v8a

# (int) Target Android API
android.api = 33

# (int) Minimum Android API supported
android.minapi = 21

# (bool) Accept SDK license automatically
android.accept_sdk_license = True


[buildozer]
# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (bool) Warn if buildozer is run as root
warn_on_root = 1
