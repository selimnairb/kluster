import sys
import os
from PySide2 import QtWidgets, QtGui, QtCore

from HSTB.shared import RegistryHelpers


# Current widgets that might be of interest:
#   BrowseListWidget - You need a list widget with browse buttons and removing of items built in?  Check this out

class DeletableListWidget(QtWidgets.QListWidget):
    """
    Inherit from the ListWidget and allow the user to press delete or backspace key to remove items
    """
    files_updated = QtCore.Signal(bool)

    def __init__(self, *args, **kwrds):
        super().__init__(*args, **kwrds)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)

    def keyReleaseEvent(self, event):
        if event.matches(QtGui.QKeySequence.Delete) or event.matches(QtGui.QKeySequence.Back):
            for itm in self.selectedItems():
                self.takeItem(self.row(itm))
        self.files_updated.emit(True)


class BrowseListWidget(QtWidgets.QWidget):
    """
    List widget with insert/remove buttons to add or remove browsed file paths.  Will emit a signal on adding/removing
    items so you can connect it to other widgets.
    """
    files_updated = QtCore.Signal(bool)

    def __init__(self, parent):
        super().__init__(parent)

        self.layout = QtWidgets.QHBoxLayout()

        self.list_widget = DeletableListWidget(self)
        list_size_policy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Preferred)
        list_size_policy.setHorizontalStretch(2)
        self.list_widget.setSizePolicy(list_size_policy)
        self.layout.addWidget(self.list_widget)

        self.button_layout = QtWidgets.QVBoxLayout()
        self.button_layout.addStretch(1)
        self.insert_button = QtWidgets.QPushButton("Insert", self)
        self.button_layout.addWidget(self.insert_button)
        self.remove_button = QtWidgets.QPushButton("Remove", self)
        self.button_layout.addWidget(self.remove_button)
        self.button_layout.addStretch(1)
        self.layout.addLayout(self.button_layout)

        self.setLayout(self.layout)

        self.opts = {}
        self.setup()
        self.insert_button.clicked.connect(self.file_browse)
        self.remove_button.clicked.connect(self.remove_item)
        self.list_widget.files_updated.connect(self.files_changed)

    def setup(self, mode='file', registry_key='pydro', app_name='browselistwidget', supported_file_extension='*.*',
              multiselect=True, filebrowse_title='Select files', filebrowse_filter='all files (*.*)'):
        """
        keyword arguments for the widget.
        """
        self.opts = vars()

    def file_browse(self):
        """
        select a file and add it to the list.
        """
        fils = []
        if self.opts['mode'] == 'file':
            msg, fils = RegistryHelpers.GetFilenameFromUserQT(self, RegistryKey=self.opts['registry_key'],
                                                              Title=self.opts['filebrowse_title'],
                                                              AppName=self.opts['app_name'],
                                                              bMulti=self.opts['multiselect'], bSave=False,
                                                              fFilter=self.opts['filebrowse_filter'])
        elif self.opts['mode'] == 'directory':
            msg, fils = RegistryHelpers.GetDirFromUserQT(self, RegistryKey=self.opts['registry_key'],
                                                         Title=self.opts['filebrowse_title'],
                                                         AppName=self.opts['app_name'])
            fils = [fils]
        if fils:
            self.add_new_files(fils)
        self.files_changed()

    def add_new_files(self, files):
        """
        Add some new files to the widget, assuming they pass the supported extension option

        Parameters
        ----------
        files: list, list of string paths to files

        """
        files = sorted(files)
        supported_ext = self.opts['supported_file_extension']
        for f in files:
            if self.list_widget.findItems(f, QtCore.Qt.MatchExactly):  # no duplicates allowed
                continue

            if self.opts['mode'] == 'file':
                fil_extension = os.path.splitext(f)[1]
                if supported_ext == '*.*':
                    self.list_widget.addItem(f)
                elif type(supported_ext) is str and fil_extension == supported_ext:
                    self.list_widget.addItem(f)
                elif type(supported_ext) is list and fil_extension in supported_ext:
                    self.list_widget.addItem(f)
                else:
                    print('{} is not a supported file extension.  Must be a string or list of file extensions.'.format(
                        supported_ext))
                    return
            else:
                self.list_widget.addItem(f)

    def return_all_items(self):
        """
        Return all the items in the list widget

        Returns
        -------
        list
            list of strings for all items in the widget
        """
        items = [self.list_widget.item(i).text() for i in range(self.list_widget.count())]
        return items

    def remove_item(self):
        """
        remove a file from the list
        """
        for itm in self.list_widget.selectedItems():
            self.list_widget.takeItem(self.list_widget.row(itm))
        self.files_changed()

    def files_changed(self):
        self.files_updated.emit(True)


class OutWindow(QtWidgets.QMainWindow):
    """
    Simple Window for viewing the widget for testing
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle('Test Window')
        self.top_widget = QtWidgets.QWidget()
        self.setCentralWidget(self.top_widget)
        layout = QtWidgets.QHBoxLayout()
        self.top_widget.setLayout(layout)

        self.widg = BrowseListWidget(self)
        self.widg.files_updated.connect(self.print_out_files)
        layout.addWidget(self.widg)

        layout.layout()
        self.setLayout(layout)
        self.centralWidget().setLayout(layout)
        self.show()

    def print_out_files(self):
        print([self.widg.list_widget.item(i).text() for i in range(self.widg.list_widget.count())])


if __name__ == '__main__':
    app = QtWidgets.QApplication()
    test_window = OutWindow()
    test_window.show()
    sys.exit(app.exec_())