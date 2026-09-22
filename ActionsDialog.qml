import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell.Io
import qs.Commons

Popup {
  id: root
  property var snapshot: ({})
  property var entries: []
  property var selected: null
  property var values: ({})
  property int stage: 0
  property bool sending: false
  property string error: ""
  property var candidates: ({})
  property int pickGeneration: 0
  property string pickerError: ""
  readonly property bool codeAction: selected && selected.id === "conflicts-save"
  readonly property bool localAction: selected && ["conflicts-prepare","conflicts-save","conflicts-discard","browse-filter","save-view","delete-view","pin","unpin","stage-comment","discard-review","download-asset","download-artifact"].indexOf(selected.id) >= 0
  readonly property bool valid: {
    if (!selected || selected.reason || sending || error) return false
    var fields = selected.fields || []
    for (var i = 0; i < fields.length; i++) {
      var value = String(values[fields[i].key] || "")
      if ((fields[i].required && !value.trim()) || value.length > 60000) return false
      if (fields[i].options && fields[i].options.indexOf(value) < 0) return false
    }
    return selected.id !== "reviewers" || !!(String(values.reviewers || "").trim() || String(values.teams || "").trim())
  }
  signal submitted(var request)
  signal legacyAction(string kind)
  modal: true
  focus: true
  padding: Style.space(12)
  width: Math.min(parent.width - 16, Style.space(codeAction ? 900 : 570))
  height: Math.min(parent.height - 16, Style.space(codeAction ? 740 : 580))
  x: (parent.width - width) / 2
  y: (parent.height - height) / 2
  closePolicy: sending ? Popup.NoAutoClose : Popup.CloseOnEscape
  background: Rectangle { color: Color.background; border.color: Color.accent; radius: Style.cornerRadius }

  function prepare(detail, choices) {
    if (sending) return
    snapshot = JSON.parse(JSON.stringify(detail || {}))
    entries = JSON.parse(JSON.stringify(choices || []))
    selected = null; values = ({}); stage = 0; error = ""
    candidates = ({}); pickerError = ""; pickGeneration++
    menu.currentIndex = 0
    open()
    Qt.callLater(function() { menu.forceActiveFocus() })
  }
  function choose(index) {
    if (sending || index < 0 || index >= entries.length) return
    selected = entries[index]
    if (selected.legacy) { var kind = selected.id; close(); legacyAction(kind); return }
    var initial = {}
    var selectedFields = selected.fields || []
    for (var i = 0; i < selectedFields.length; i++) initial[selectedFields[i].key] = selectedFields[i].value || ""
    values = initial; error = ""
    stage = selected.fields.length ? 1 : 2
    Qt.callLater(function() {
      if (stage === 1 && fields.count) fields.itemAt(0).firstControl.forceActiveFocus()
      else backButton.forceActiveFocus()
    })
  }
  function setValue(key, value) { var copy = Object.assign({}, values); copy[key] = value; values = copy }
  function canPick(key) { return ["repo","labels","assignees","reviewers","milestone","head","base","ref","branch","target"].indexOf(key) >= 0 }
  function pick(key, next) {
    if (picker.running) return
    var current = candidates[key]
    picker.request = {op:"pick",field:key,repo:values.repo || (snapshot.target ? snapshot.target.repo : ""),page:next && current ? current.page + 1 : 1}
    picker.requestGeneration = pickGeneration
    pickerError = ""
    picker.running = true
  }
  function goBack() {
    if (sending) return
    if (stage === 0 || error) { close(); return }
    if (stage === 2 && selected.fields.length && !error) stage = 1
    else { stage = 0; error = "" }
    Qt.callLater(function() { if (stage === 0) menu.forceActiveFocus(); else backButton.forceActiveFocus() })
  }
  function review() {
    if (!valid) return
    if (selected.id === "browse-filter") { stage = 2; confirm(); return }
    stage = 2
    Qt.callLater(function() { backButton.forceActiveFocus() })
  }
  Process {
    id: picker
    property var request: ({})
    property int requestGeneration: 0
    command: ["python3","-B",Qt.resolvedUrl("reader_client.py").toString().replace(/^file:\/\//, "")]
    stdinEnabled: true
    onStarted: write(JSON.stringify(request)+"\n")
    stdout: StdioCollector { id: pickOutput; waitForEnd: true }
    onExited: function(code) {
      if (requestGeneration !== root.pickGeneration || !root.visible) return
      try {
        var result = JSON.parse(pickOutput.text || "{}")
        if (!result.ok) { root.pickerError = result.error || "Could not load choices."; return }
        var data = Object.assign({},root.candidates)
        data[request.field] = result
        root.candidates = data
      } catch (e) { root.pickerError = "Could not read choices." }
    }
  }
  function confirm() {
    if (!valid || stage !== 2) return
    sending = true
    submitted({op:"action", action:selected.id, item:snapshot.target || {},
      expected:selected.expected || {}, values:JSON.parse(JSON.stringify(values)), confirmed:true})
  }
  function finish(message) {
    sending = false; error = message || ""
    if (!error) close()
  }
  function confirmationText() {
    if (!selected) return ""
    var lines = []
    var expected = selected.expected || {}
    if (selected.id.indexOf("conflicts-") === 0 && expected.baseSha) {
      lines.push("PR source: " + expected.headRepo + ":" + expected.headRef + " @ " + expected.headSha.substring(0,12))
      lines.push("Merge target: " + expected.baseRepo + ":" + expected.baseRef + " @ " + expected.baseSha.substring(0,12))
    } else if (expected.headSha) lines.push("Commit " + expected.headSha.substring(0,12) + " → " + expected.baseRef)
    if (expected.head_sha) lines.push("Commit " + expected.head_sha.substring(0,12) + " · attempt " + expected.run_attempt)
    for (var i = 0; i < selected.fields.length; i++) {
      var f = selected.fields[i]
      lines.push(f.label + ":\n" + (values[f.key] || "(empty)"))
    }
    return lines.join("\n\n")
  }
  component LabelText: Text {
    Layout.fillWidth: true
    color: Color.foreground
    textFormat: Text.PlainText
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    wrapMode: Text.WrapAnywhere
  }
  component ActionButton: Button {
    id: button
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
    padding: Style.space(8)
    Keys.onPressed: function(event) {
      if (event.key === Qt.Key_Left || event.key === Qt.Key_Backspace) { root.goBack(); event.accepted = true }
      else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Right) {
        if (!event.isAutoRepeat && enabled) clicked()
        event.accepted = true
      } else if (event.key === Qt.Key_Up || event.key === Qt.Key_Down) {
        if (button === backButton && primaryButton.enabled) primaryButton.forceActiveFocus()
        else backButton.forceActiveFocus()
        event.accepted = true
      }
    }
    contentItem: Text { text: button.text; font: button.font; color: button.enabled ? Color.foreground : Color.muted; horizontalAlignment: Text.AlignHCenter }
    background: Rectangle { color: Style.hoverFillFor(Color.foreground, Color.accent); border.width: button.activeFocus ? 1 : 0; border.color: Color.accent; radius: Style.cornerRadius }
  }
  contentItem: ColumnLayout {
    spacing: Style.space(8)
    LabelText { text: root.stage === 0 || !root.selected ? "Actions" : root.selected.label; font.bold: true; font.pixelSize: Style.font.subtitle }
    LabelText {
      text: root.snapshot.target ? root.snapshot.target.repo + (root.snapshot.target.number ? " #" + root.snapshot.target.number : "") + "\n" + (root.snapshot.title || "") : "New issue"
      color: Color.accent
      maximumLineCount: 3
      elide: Text.ElideRight
    }
    ListView {
      id: menu
      objectName: "actionMenu"
      Layout.fillWidth: true
      Layout.fillHeight: true
      visible: root.stage === 0
      clip: true
      model: root.entries
      spacing: Style.space(2)
      boundsBehavior: Flickable.StopAtBounds
      ScrollBar.vertical: ScrollBar {}
      Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Up || event.key === Qt.Key_K) currentIndex = Math.max(0, currentIndex - 1)
        else if (event.key === Qt.Key_Down || event.key === Qt.Key_J) currentIndex = Math.min(count - 1, currentIndex + 1)
        else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Right) { if (!event.isAutoRepeat) root.choose(currentIndex) }
        else if (event.key === Qt.Key_Left || event.key === Qt.Key_Backspace || event.key === Qt.Key_Escape) root.close()
        else { event.accepted = false; return }
        positionViewAtIndex(currentIndex, ListView.Contain)
        event.accepted = true
      }
      delegate: ItemDelegate {
        required property var modelData
        required property int index
        width: menu.width
        height: Style.space(34)
        text: modelData.label + "  ›"
        onClicked: { menu.currentIndex = index; root.choose(index) }
        contentItem: Text { text: parent.text; color: modelData.reason ? Color.muted : Color.foreground; font.family: Style.font.family; font.pixelSize: Style.font.body; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
        background: Rectangle { color: index === menu.currentIndex ? Style.selectedFillFor(Color.foreground, Color.accent) : "transparent"; border.width: index === menu.currentIndex ? 1 : 0; border.color: Color.accent }
      }
    }
    ScrollView {
      id: formScroll
      Layout.fillWidth: true
      Layout.fillHeight: true
      visible: root.stage > 0
      clip: true
      contentWidth: availableWidth
      ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
      ColumnLayout {
        width: formScroll.availableWidth
        spacing: Style.space(10)
        LabelText { text: root.selected ? root.selected.description : "" }
        LabelText { visible: !!root.selected && !!root.selected.reason; text: root.selected ? root.selected.reason || "" : ""; color: Color.urgent }
        Repeater {
          id: fields
          model: root.stage === 1 && root.selected ? root.selected.fields : []
          delegate: ColumnLayout {
            required property var modelData
            readonly property var firstControl: modelData.options ? methodChooser : editor
            Layout.fillWidth: true
            LabelText { text: modelData.label + (modelData.required ? " *" : "") }
            RowLayout {
              Layout.fillWidth: true
              visible: root.canPick(modelData.key) && !modelData.options
              Button { text: "Browse choices"; enabled: !picker.running; onClicked: root.pick(modelData.key,false) }
              Button { text: "Next choices"; visible: !!root.candidates[modelData.key] && root.candidates[modelData.key].more; enabled: !picker.running; onClicked: root.pick(modelData.key,true) }
            }
            ComboBox {
              Layout.fillWidth: true
              visible: !!root.candidates[modelData.key]
              textRole: "label"
              model: [{value:"",label:"Select to insert…"}].concat(root.candidates[modelData.key] ? root.candidates[modelData.key].items : [])
              onActivated: if (currentIndex > 0) {
                var value = model[currentIndex].value
                var previous = root.values[modelData.key] || ""
                root.setValue(modelData.key, modelData.multiline ? previous + (previous ? "\n" : "") + value : value)
                currentIndex = 0
              }
            }
            ComboBox {
              id: methodChooser
              Layout.fillWidth: true
              visible: !!modelData.options
              model: modelData.options || []
              currentIndex: model.indexOf(root.values[modelData.key])
              onActivated: root.setValue(modelData.key, currentText)
              Accessible.name: modelData.label
            }
            ComboBox {
              Layout.fillWidth: true
              visible: !!modelData.suggestions
              model: ["Insert a suggestion…"].concat(modelData.suggestions || [])
              onActivated: if (currentIndex > 0) {
                var value = root.values[modelData.key] || ""
                root.setValue(modelData.key, value + (value ? "\n" : "") + currentText)
                currentIndex = 0
              }
            }
            ScrollView {
              Layout.fillWidth: true
              Layout.preferredHeight: Style.space(modelData.code ? 260 : (modelData.multiline ? 110 : 42))
              visible: !modelData.options
              TextArea {
                id: editor
                objectName: "field_" + modelData.key
                text: root.values[modelData.key] || ""
                onTextChanged: if (activeFocus) root.setValue(modelData.key, text)
                textFormat: TextEdit.PlainText
                wrapMode: modelData.code ? TextEdit.NoWrap : TextEdit.Wrap
                selectByMouse: true
                color: Color.foreground
                font.family: Style.font.family
                font.pixelSize: Style.font.body
                Accessible.name: modelData.label
                background: Rectangle { color: Color.background; border.color: editor.activeFocus ? Color.accent : Color.muted }
                Keys.onPressed: function(event) {
                  if (event.key === Qt.Key_Escape) { root.goBack(); event.accepted = true }
                  else if (!modelData.multiline && (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)) { primaryButton.forceActiveFocus(); event.accepted = true }
                  else if (event.key === Qt.Key_Tab) { nextItemInFocusChain().forceActiveFocus(); event.accepted = true }
                  else if (event.key === Qt.Key_Backtab) { nextItemInFocusChain(false).forceActiveFocus(); event.accepted = true }
                }
                onActiveFocusChanged: if (activeFocus) {
                  var top = mapToItem(formScroll.contentItem, 0, 0).y
                  formScroll.contentItem.contentY = Math.max(0, Math.min(top, formScroll.contentHeight - formScroll.height))
                }
              }
            }
          }
        }
        LabelText { visible: root.stage === 2; text: root.confirmationText() }
        LabelText { visible: root.stage === 2; text: root.localAction ? "Confirm to update your local workspace." : "Confirm to apply this action on GitHub."; color: Color.accent }
        LabelText { visible: !!root.pickerError; text: root.pickerError; color: Color.urgent }
        LabelText { visible: !!root.error; text: root.error; color: Color.urgent }
      }
    }
    LabelText { visible: root.stage === 0; text: "↑ ↓: select · Enter / →: open · ← / Backspace: back"; color: Color.muted; font.pixelSize: Style.font.caption }
    RowLayout {
      Layout.fillWidth: true
      visible: root.stage > 0
      ActionButton { id: backButton; objectName: "actionBack"; text: root.error ? "Close and refresh" : "← Back"; enabled: !root.sending; onClicked: root.goBack() }
      Item { Layout.fillWidth: true }
      ActionButton { id: primaryButton; objectName: "actionConfirm"; text: root.sending ? "Submitting…" : (root.stage === 1 ? "Review action →" : "Confirm"); enabled: root.valid; onClicked: if (root.stage === 1) root.review(); else root.confirm() }
    }
  }
}
