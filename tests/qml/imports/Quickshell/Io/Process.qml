import QtQuick
QtObject {
  property var command: []
  property bool running: false
  property bool stdinEnabled: false
  property var stdout
  property var stderr
  signal started()
  signal exited(int code)
  function write(text) { throw new Error("Keyboard tests must not start a process") }
}
