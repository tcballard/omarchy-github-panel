import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import qs.Commons

Popup {
  id: root
  property var snapshot: null
  property string actionKind: ""
  property string selectedMethod: ""
  property bool sending: false
  property string error: ""
  readonly property string actionLabel: actionKind === "merge" ? "Merge pull request" : (actionKind === "approve" ? "Approve pull request" : "Request changes")
  readonly property var pr: snapshot ? snapshot.pr : null
  readonly property bool canSubmit: !!pr && !sending && error.length === 0 && (actionKind === "merge" ? pr.canMerge && pr.mergeMethods.indexOf(selectedMethod) >= 0 : pr.canReview && note.text.length <= 60000 && (actionKind !== "request-changes" || note.text.trim().length > 0))
  signal submitted(var request)
  modal: true
  focus: true
  padding: Style.space(12)
  width: Math.min(parent.width - 16, Style.space(550))
  height: Math.min(parent.height - 16, contentColumn.implicitHeight + padding * 2)
  x: (parent.width - width) / 2
  y: (parent.height - height) / 2
  closePolicy: sending ? Popup.NoAutoClose : Popup.CloseOnEscape
  background: Rectangle { color: Color.background; border.color: Color.accent; radius: Style.cornerRadius }

  function prepare(kind, value) {
    if (sending || !value || !value.pr) return
    snapshot = JSON.parse(JSON.stringify(value))
    actionKind = kind
    selectedMethod = pr.mergeMethods.length ? pr.mergeMethods[0] : ""
    note.text = ""
    error = ""
    open()
    Qt.callLater(function() { cancelButton.forceActiveFocus(Qt.OtherFocusReason) })
  }

  function confirm() {
    if (!canSubmit) return
    sending = true
    error = ""
    submitted({op: "action", action: actionKind, item: snapshot.target,
      expectedHeadSha: pr.headSha, expectedBase: pr.baseRef, confirmed: true,
      mergeMethod: selectedMethod, body: note.text})
  }

  function finish(message) {
    sending = false
    error = message || ""
    if (!error) close()
  }

  component DialogText: Text {
    textFormat: Text.PlainText
    color: Color.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    wrapMode: Text.WrapAnywhere
    Layout.fillWidth: true
  }
  component DialogButton: Button {
    id: button
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
    padding: Style.space(8)
    Keys.onReturnPressed: function(event) { if (!event.isAutoRepeat) button.clicked() }
    Keys.onEnterPressed: function(event) { if (!event.isAutoRepeat) button.clicked() }
    contentItem: Text { text: button.text; textFormat: Text.PlainText; font: button.font; color: button.enabled ? Color.foreground : Color.muted; horizontalAlignment: Text.AlignHCenter }
    background: Rectangle {
      radius: Style.cornerRadius
      color: button.down || button.checked ? Style.selectedFillFor(Color.foreground, Color.accent) : Style.hoverFillFor(Color.foreground, Color.accent)
      border.width: button.activeFocus ? 1 : 0
      border.color: Color.accent
    }
  }

  contentItem: ScrollView {
    id: dialogScroll
    clip: true
    contentWidth: availableWidth
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    Keys.onPressed: function(event) {
      if (!root.sending && (event.key === Qt.Key_Escape || (!note.activeFocus && (event.key === Qt.Key_Left || event.key === Qt.Key_Backspace)))) {
        root.close()
        event.accepted = true
      } else event.accepted = false
    }
    ColumnLayout {
      id: contentColumn
      width: dialogScroll.availableWidth
      spacing: Style.space(10)
      DialogText { text: root.actionLabel; font.bold: true; font.pixelSize: Style.font.subtitle }
      DialogText { text: root.snapshot ? root.snapshot.target.repo + " #" + root.snapshot.target.number + "\n" + root.snapshot.title : ""; color: Color.accent }
      DialogText { text: root.pr ? root.pr.headRef + " → " + root.pr.baseRef + "\nCommit " + root.pr.headSha.substring(0, 12) : "" }
      DialogText {
        visible: root.actionKind === "merge"
        text: root.pr ? "Readiness: " + root.pr.mergeState + (root.pr.mergeReason ? "\n" + root.pr.mergeReason : "") : ""
      }
      DialogText { text: root.pr ? "Checks: " + (root.pr.checkSummary || "Not available; see the Checks tab") : "" }
      DialogText { visible: root.actionKind !== "merge" && !!root.pr && root.pr.reviewReason.length > 0; text: root.pr ? root.pr.reviewReason : "" }
      DialogText { visible: root.actionKind === "merge"; text: "Merge method"; font.bold: true }
      Flow {
        Layout.fillWidth: true
        visible: root.actionKind === "merge"
        spacing: Style.space(6)
        Repeater {
          model: root.pr ? root.pr.mergeMethods : []
          delegate: DialogButton {
            required property string modelData
            text: modelData === "squash" ? "Squash" : (modelData === "rebase" ? "Rebase" : "Merge commit")
            checked: root.selectedMethod === modelData
            enabled: !root.sending
            onClicked: root.selectedMethod = modelData
          }
        }
      }
      DialogText {
        visible: root.actionKind !== "merge"
        text: root.actionKind === "approve" ? "Review note (optional)" : "Explain the changes needed"
      }
      ScrollView {
        Layout.fillWidth: true
        Layout.preferredHeight: Style.space(110)
        visible: root.actionKind !== "merge"
        TextArea {
          id: note
          objectName: "reviewNote"
          textFormat: TextEdit.PlainText
          color: Color.foreground
          wrapMode: TextEdit.Wrap
          selectByMouse: true
          readOnly: root.sending
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          Accessible.name: "Review note"
          background: Rectangle { color: Color.background; border.color: note.activeFocus ? Color.accent : Color.muted; radius: Style.cornerRadius }
          // Leave text editing keys to the editor; Tab moves to the explicit submit button.
          KeyNavigation.tab: confirmButton
          KeyNavigation.backtab: cancelButton
        }
      }
      DialogText { visible: root.error.length > 0; text: root.error; color: Color.urgent }
      DialogText { text: root.sending ? "Submitting to GitHub…" : ""; visible: root.sending; color: Color.accent }
      RowLayout {
        Layout.fillWidth: true
        DialogButton { id: cancelButton; objectName: "cancelPRAction"; text: "Cancel"; enabled: !root.sending; onClicked: root.close() }
        Item { Layout.fillWidth: true }
        DialogButton { id: confirmButton; objectName: "confirmPRAction"; text: root.actionLabel; enabled: root.canSubmit; onClicked: root.confirm() }
      }
    }
  }
}
