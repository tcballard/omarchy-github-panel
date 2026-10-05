import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import qs.Commons

ColumnLayout {
  id: root
  required property var entry
  property bool loaded: false
  Layout.fillWidth: true
  Button {
    id: loadButton
    objectName: "loadImage"
    text: root.loaded ? "Hide image" : "Load image: " + root.entry.label
    Accessible.name: text
    contentItem: Text {
      text: loadButton.text
      textFormat: Text.PlainText
      font: loadButton.font
      color: loadButton.palette.buttonText
      horizontalAlignment: Text.AlignHCenter
      verticalAlignment: Text.AlignVCenter
      elide: Text.ElideRight
    }
    onClicked: root.loaded = !root.loaded
  }
  Image {
    id: preview
    objectName: "previewImage"
    Layout.fillWidth: true
    Layout.preferredHeight: visible ? Math.min(400, implicitHeight || 250) : 0
    visible: root.loaded
    source: root.loaded ? root.entry.url : ""
    sourceSize: Qt.size(1200, 800)
    asynchronous: true
    cache: false
    fillMode: Image.PreserveAspectFit
  }
  Text {
    visible: root.loaded
    Layout.fillWidth: true
    text: (preview.status === Image.Error ? "Image unavailable (private attachments may need browser authentication): " : preview.status === Image.Loading ? "Loading image from " : "Image from ") + root.entry.url
    textFormat: Text.PlainText
    color: Color.muted
    wrapMode: Text.WrapAnywhere
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
  }
}
