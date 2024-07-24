# AudioHelper

# Editing the GUI
The Qt Designer portion of Qt Creator was used to
draw the GUI window.  The corresponding design is 
captured in the ui_AudioHelperGUI.ui file.  Only edit
the .ui file with Qt Designer.

The .ui file is converted to python code with:

    pyuic5 -o ui_AudioHelperGUI.py ui_AudioHelperGUI.ui

The resulting file is then imported into the AudioHelperGUI.py.
