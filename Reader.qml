import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons

Rectangle {
  id: root
  property var service: null
  property var item: null
  property var detail: null
  property var history: []
  property var drafts: ({})
  property string tabId: "conversation"
  property int selectedBlock: -1
  property string error: ""
  property string notice: ""
  property bool composing: false
  property int generation: 0
  property var pending: null
  property string findText: ""
  property int findOffset: 0
  property string externalLink: ""
  property bool restorePosition: false
  property string readerAccount: ""
  property bool busy: worker.running || pending !== null
  property bool posting: (worker.running && worker.request && worker.request.op === "action") || (pending !== null && pending.request.op === "action")
  readonly property bool actionOpen: prAction.visible || actions.visible
  readonly property var tabs: detail ? detail.tabs : []
  readonly property var activeTab: {
    for (var i = 0; i < tabs.length; i++) if (tabs[i].id === tabId) return tabs[i]
    return tabs.length ? tabs[0] : null
  }
  readonly property string draftKey: stateKey(item)
  signal back()
  Component.onCompleted: readerAccount = service && service.verifiedAccount ? service.verifiedAccount : ""
  color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.025)
  radius: Style.cornerRadius

  function stateKey(value) {
    if (!value) return ""
    var fields = ["repo","kind","number","sha","path","ref","collection","section","page","cursor","view","query","owner","state","scope","mode","reason","workflow","branch","thread","comment","tag","scan"]
    var identity = []
    for (var i = 0; i < fields.length; i++) identity.push(value[fields[i]] || "")
    if (value.kind === "notification") identity.push(value.id)
    return JSON.stringify(identity)
  }

  function saveDraft() {
    if (draftKey) {
      drafts[draftKey] = composer.text
      if (service && typeof service.saveLocal === "function") service.saveLocal("drafts", draftKey, composer.text)
    }
  }
  function savePosition() {
    if (draftKey && detail && service && typeof service.saveLocal === "function")
      service.saveLocal("positions", draftKey, {tab:tabId,y:scroll.contentItem.contentY})
  }
  function openLinkDialog() { linkPopup.open(); Qt.callLater(function() { linkInput.forceActiveFocus() }) }
  function openLink(url) {
    if (busy || actionOpen) return
    externalLink = ""
    if (/^https:\/\//.test(url) && !/^https:\/\/github\.com\//.test(url)) {
      externalLink = url
      notice = "External reference: " + url
      return
    }
    queue({op:"navigate",url:url,repo:item ? item.repo : ""}, false)
  }
  function findNext() {
    if (!findText || !activeTab) return
    var start = Math.max(0, selectedBlock)
    for (var j = 0; j < activeTab.blocks.length; j++) {
      var i = (start + j) % activeTab.blocks.length
      var b = activeTab.blocks[i]
      var position = b.body.toLowerCase().indexOf(findText.toLowerCase(), j === 0 ? findOffset : 0)
      if (position >= 0) {
        selectedBlock = i
        findOffset = position + findText.length
        var entry = contentBlocks.itemAt(i)
        if (entry) {
          entry.bodyControl.select(position, position + findText.length)
          var rect = entry.bodyControl.positionToRectangle(position)
          scroll.contentItem.contentY = Math.min(entry.bodyControl.mapToItem(scroll.contentItem,0,rect.y).y, Math.max(0,scroll.contentHeight-scroll.height))
        }
        return
      }
    }
    findOffset = 0
    notice = "No further matches on this page. Find again to wrap."
  }

  Connections {
    target: root.service
    ignoreUnknownSignals: true
    function onLocalStateLoaded() {
      if (root.service && root.service.localDrafts) {
        root.drafts = Object.assign({}, root.service.localDrafts, root.drafts)
        if (!composer.text && root.draftKey) composer.text = root.drafts[root.draftKey] || ""
      }
    }
    function onVerifiedAccountChanged() {
      var initial = root.readerAccount === ""
      root.readerAccount = root.service.verifiedAccount
      root.drafts = ({})
      root.detail = null
      root.history = []
      root.generation++
      root.pending = null
      if (!initial) root.item = null
      composer.text = ""
      if (initial && root.item) root.refresh()
    }
  }

  function showItem(value, nested) {
    if (posting || actionOpen) return
    saveDraft()
    savePosition()
    if (nested && item) history = history.concat([item])
    else if (!nested) history = []
    item = JSON.parse(JSON.stringify(value))
    generation++
    detail = null
    error = ""
    notice = ""
    selectedBlock = -1
    tabId = "conversation"
    composer.text = drafts[draftKey] || (service && service.localDrafts ? service.localDrafts[draftKey] : "") || ""
    composing = composer.text.length > 0
    findText = ""
    findOffset = 0
    restorePosition = true
    refresh()
    focusReader()
  }

  function goBack() {
    if (posting || actionOpen) return
    saveDraft()
    savePosition()
    if (history.length) {
      var previous = history[history.length - 1]
      history = history.slice(0, -1)
      var saved = history
      showItem(previous, false)
      history = saved
    } else {
      generation++
      pending = null
      root.back()
    }
  }

  function refresh() {
    if (!item || posting || actionOpen) return
    error = ""
    queue({op: "detail", item: item, page: 1}, false)
  }

  function loadMore() {
    if (!detail || busy) return
    queue({op: "detail", item: item, page: detail.nextPage || 1, cursor: detail.nextCursor || null}, true)
  }

  function openActions() {
    if (busy || !detail || detail.cached) return
    var choices = []
    if (detail.pr) choices = [
      {id:"approve", label:"Approve pull request", legacy:true},
      {id:"request-changes", label:"Request changes", legacy:true},
      {id:"merge", label:"Merge pull request", legacy:true}]
    choices = choices.concat(detail.actions || [])
    choices.push(createIssueChoice(item ? item.repo : ""))
    actions.prepare(detail, choices)
  }

  function createIssueChoice(repo) {
    return {id:"create-issue", label:"Create issue", description:"Create a new issue in this repository.", expected:{}, fields:[
      {key:"repo", label:"Repository (owner/name)", value:repo, required:true},
      {key:"title", label:"Title", value:"", required:true},
      {key:"body", label:"Description", value:"", multiline:true}]}
  }

  function newIssue(repo) {
    if (busy || actionOpen) return
    actions.prepare({title:"New issue",target:{repo:repo}}, [createIssueChoice(repo)])
    actions.choose(0)
  }

  function submit(action) {
    if (busy || !detail) return
    saveDraft()
    error = ""
    notice = ""
    queue({op: "action", action: action, item: item, body: action === "reply" ? composer.text : ""}, false)
  }

  function queue(request, append) {
    request.account = service && service.verifiedAccount ? service.verifiedAccount : ""
    pending = {request: request, generation: generation, append: append}
    startPending()
  }

  function startPending() {
    if (worker.running || pending === null) return
    var next = pending
    pending = null
    worker.request = next.request
    worker.requestGeneration = next.generation
    worker.append = next.append
    worker.running = true
  }

  function navigationState() {
    var controls = []
    keyboardControls(root, controls)
    var focused = "reader"
    for (var i = 0; i < controls.length; i++) if (controls[i].activeFocus)
      focused = controls[i] === composer ? "composer" : controls[i].text
    return {tab: activeTab ? activeTab.id : "", focused: focused, composing: composing,
      draftLength: composer.text.length, scrollY: scroll.contentItem.contentY, busy: busy, error: error}
  }

  function focusReader() {
    root.forceActiveFocus(Qt.OtherFocusReason)
  }

  function startReply() {
    if (busy || !detail || !detail.canReply) return
    composing = true
    composer.forceActiveFocus(Qt.OtherFocusReason)
  }

  function selectTab(index) {
    if (!tabs.length) return
    var i = (index + tabs.length) % tabs.length
    selectedBlock = -1
    tabId = tabs[i].id
    scroll.contentItem.contentY = 0
    savePosition()
    var button = tabButtons.itemAt(i)
    if (button) button.forceActiveFocus(Qt.TabFocusReason)
  }

  function moveTab(delta) {
    var index = 0
    for (var i = 0; i < tabs.length; i++) if (activeTab && tabs[i].id === activeTab.id) index = i
    selectTab(index + delta)
  }

  function keyboardControls(parent, result) {
    if (!parent.visible || !parent.enabled) return
    if (parent.keyboardControl === true) {
      result.push(parent)
      return
    }
    for (var i = 0; i < parent.children.length; i++) keyboardControls(parent.children[i], result)
  }

  function moveFocus(backward) {
    var controls = []
    keyboardControls(root, controls)
    if (!controls.length) return
    var index = backward ? 0 : -1
    for (var i = 0; i < controls.length; i++) if (controls[i].activeFocus) index = i
    var next = controls[(index + (backward ? -1 : 1) + controls.length) % controls.length]
    next.forceActiveFocus(backward ? Qt.BacktabFocusReason : Qt.TabFocusReason)
    // Bring buttons embedded in long threads and CI job lists into view.
    var parent = next.parent
    while (parent && parent !== scroll.contentItem) parent = parent.parent
    if (parent) {
      var y = next.mapToItem(scroll.contentItem, 0, 0).y
      if (y < scroll.contentItem.contentY) scroll.contentItem.contentY = y
      else if (y + next.height > scroll.contentItem.contentY + scroll.height)
        scroll.contentItem.contentY = y + next.height - scroll.height
    }
  }

  function drillItems() {
    var result = []
    if (!activeTab) return result
    for (var i = 0; i < activeTab.blocks.length; i++)
      if (activeTab.blocks[i].action || (activeTab.blocks[i].operations || []).length) result.push(i)
    return result
  }

  function selectBlock(delta) {
    var items = drillItems()
    if (!items.length) return false
    var at = items.indexOf(selectedBlock)
    at = at < 0 ? (delta < 0 ? items.length - 1 : 0) : Math.max(0, Math.min(items.length - 1, at + delta))
    selectedBlock = items[at]
    var entry = contentBlocks.itemAt(selectedBlock)
    if (entry) {
      entry.drillButton.forceActiveFocus(Qt.OtherFocusReason)
      var y = entry.mapToItem(scroll.contentItem, 0, 0).y
      scroll.contentItem.contentY = Math.max(0, Math.min(Math.max(0, scroll.contentHeight - scroll.height), y))
    }
    return true
  }

  function openBlock(index) {
    if (busy || actionOpen || !activeTab) return
    var block = activeTab.blocks[index]
    if (block.action) showItem(block.action, true)
    else if (block.operations && block.operations.length) actions.prepare(detail, block.operations)
  }

  function enterDetail() {
    var controls = []
    keyboardControls(root, controls)
    for (var i = 0; i < controls.length; i++) {
      if (controls[i].activeFocus) {
        if (controls[i].drillControl) controls[i].clicked()
        else focusReader()
        return
      }
    }
    var items = drillItems()
    if (items.length) {
      var index = selectedBlock < 0 ? items[0] : selectedBlock
      openBlock(index)
    } else focusReader()
  }

  function handleKey(event) {
    event.accepted = false
    if (actionOpen || linkPopup.visible) return
    if (findInput.activeFocus) {
      if (event.key === Qt.Key_Escape) { focusReader(); event.accepted = true }
      return
    }
    var tab = event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab
    var shift = (event.modifiers & Qt.ShiftModifier) !== 0
    var control = (event.modifiers & Qt.ControlModifier) !== 0
    if (control && event.key === Qt.Key_F) { findInput.forceActiveFocus(); findInput.selectAll(); event.accepted = true; return }
    if (tab && !(event.modifiers & (Qt.AltModifier | Qt.MetaModifier))) {
      if (control && !composer.activeFocus) moveTab(shift ? -1 : 1)
      else moveFocus(shift || event.key === Qt.Key_Backtab)
      event.accepted = true
      return
    }
    if (composer.activeFocus) {
      if (event.key === Qt.Key_Escape) {
        saveDraft()
        composing = false
        focusReader()
        event.accepted = true
      }
      // Letters, Enter, cursor movement and editing shortcuts belong to the draft.
      return
    }
    if (event.modifiers !== Qt.NoModifier) return
    if (event.key === Qt.Key_Escape || event.key === Qt.Key_Backspace || event.key === Qt.Key_Left || event.key === Qt.Key_H) {
      goBack()
    } else if (event.key === Qt.Key_R) {
      refresh()
    } else if (event.key === Qt.Key_A) {
      openActions()
    } else if (event.key === Qt.Key_C) {
      startReply()
    } else if (event.key === Qt.Key_Right || event.key === Qt.Key_L) {
      enterDetail()
    } else if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && root.activeFocus) {
      enterDetail()
    } else if (event.key === Qt.Key_BracketLeft) {
      moveTab(-1)
    } else if (event.key === Qt.Key_BracketRight) {
      moveTab(1)
    } else if (event.key >= Qt.Key_1 && event.key <= Qt.Key_9) {
      if (event.key - Qt.Key_1 < tabs.length) selectTab(event.key - Qt.Key_1)
    } else if ([Qt.Key_Up, Qt.Key_Down, Qt.Key_K, Qt.Key_J, Qt.Key_PageUp, Qt.Key_PageDown, Qt.Key_Home, Qt.Key_End].indexOf(event.key) >= 0) {
      if ([Qt.Key_Up, Qt.Key_Down, Qt.Key_K, Qt.Key_J].indexOf(event.key) >= 0 && selectBlock([Qt.Key_Up, Qt.Key_K].indexOf(event.key) >= 0 ? -1 : 1)) {
        event.accepted = true
        return
      }
      var maximum = Math.max(0, scroll.contentHeight - scroll.height)
      var amount = (event.key === Qt.Key_PageUp || event.key === Qt.Key_PageDown) ? scroll.height * 0.8 : 44
      if ([Qt.Key_Up, Qt.Key_K, Qt.Key_PageUp].indexOf(event.key) >= 0) amount = -amount
      var y = scroll.contentItem.contentY + amount
      if (event.key === Qt.Key_Home) y = 0
      if (event.key === Qt.Key_End) y = maximum
      scroll.contentItem.contentY = Math.max(0, Math.min(maximum, y))
    } else {
      return
    }
    event.accepted = true
  }

  PRActionDialog {
    id: prAction
    objectName: "prActionDialog"
    parent: root
    onSubmitted: function(request) { root.error = ""; root.notice = ""; root.queue(request, false) }
    onClosed: root.focusReader()
  }

  ActionsDialog {
    id: actions
    objectName: "lifecycleActions"
    parent: root
    onSubmitted: function(request) { root.error = ""; root.notice = ""; root.queue(request, false) }
    onLegacyAction: function(kind) { prAction.prepare(kind, root.detail) }
    onClosed: { if (!root.item) root.back(); else root.focusReader() }
  }

  Keys.priority: Keys.BeforeItem
  Keys.onPressed: function(event) { root.handleKey(event) }

  Process {
    id: worker
    objectName: "readerWorker"
    property var request: null
    property int requestGeneration: 0
    property bool append: false
    command: ["python3", "-B", Qt.resolvedUrl("reader_client.py").toString().replace(/^file:\/\//, "")]
    stdinEnabled: true
    onStarted: write(JSON.stringify(request) + "\n")
    stdout: StdioCollector { id: output; waitForEnd: true }
    stderr: StdioCollector { id: errors; waitForEnd: true }
    onExited: function(code) {
      if (requestGeneration === root.generation) {
        try {
          var value = JSON.parse(output.text || "{}")
          if (!value.ok) {
            root.error = String(value.error || errors.text || "GitHub did not return a response.")
            if (request.op === "action") {
              root.error += " Refresh the thread before retrying if the request may have reached GitHub."
              if (prAction.visible) prAction.finish(root.error)
              if (actions.visible) {
                actions.finish(root.error)
                root.detail = null
              }
            }
          } else if (request.op === "navigate") {
            root.showItem(value.navigate, true)
          } else if (request.op === "action") {
            root.notice = value.message
            if (request.action === "reply") {
              composer.text = ""
              root.drafts[root.draftKey] = ""
              if (root.service && typeof root.service.saveLocal === "function") root.service.saveLocal("drafts",root.draftKey,"")
              root.composing = false
              root.queue({op: "detail", item: root.item, page: 1}, false)
            } else if (request.action === "mark-read" && root.detail) {
              var updated = Object.assign({}, root.detail)
              updated.threadId = ""
              root.detail = updated
            }
            if (["approve", "request-changes", "merge"].indexOf(request.action) >= 0) {
              prAction.finish("")
              // Remove the old action snapshot immediately; a refresh will supply current readiness.
              var refreshed = Object.assign({}, root.detail)
              refreshed.pr = null
              root.detail = refreshed
              root.queue({op: "detail", item: root.item, page: 1}, false)
            }
            if (actions.visible) {
              // Clear the old snapshot before closing the modal and refreshing.
              root.detail = null
              if (value.target) {
                root.item = value.target
                root.history = []
                root.tabId = "conversation"
                composer.text = ""
                root.composing = false
              }
              actions.finish("")
              if (root.item) root.queue({op: "detail", item: root.item, page: 1}, false)
            }
            if (root.service && !value.local) root.service.refresh()
          } else {
            if (append && root.detail) {
              for (var i = 0; i < value.tabs.length; i++) {
                if (value.tabs[i].id !== "conversation") continue
                for (var j = 0; j < root.detail.tabs.length; j++) {
                  if (root.detail.tabs[j].id === "conversation")
                    value.tabs[i].blocks = root.detail.tabs[j].blocks.concat(value.tabs[i].blocks)
                }
              }
            }
            root.detail = value
            if (!append) {
              scroll.contentItem.contentY = 0
              if (root.restorePosition && root.service && root.service.localPositions) {
                var position = root.service.localPositions[root.draftKey]
                if (position) {
                  root.tabId = position.tab
                  Qt.callLater(function() { scroll.contentItem.contentY = Math.max(0,Math.min(position.y,scroll.contentHeight-scroll.height)) })
                }
              }
              root.restorePosition = false
            }
          }
        } catch (e) {
          root.error = "Could not read GitHub's response. " + String(errors.text || e).substring(0, 300)
          if (request.op === "action") {
            if (prAction.visible) prAction.finish(root.error + " Refresh the thread before retrying.")
            if (actions.visible) { actions.finish(root.error + " Refresh before retrying."); root.detail = null }
          }
        }
      }
      Qt.callLater(root.startPending)
    }
  }

  component DeskButton: Button {
    id: button
    property bool keyboardControl: true
    property bool drillControl: false
    Keys.priority: Keys.BeforeItem
    Keys.onPressed: function(event) {
      root.handleKey(event)
      if (!event.accepted && event.modifiers === Qt.NoModifier && (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)) {
        event.accepted = true
        if (!event.isAutoRepeat) button.clicked()
      }
    }
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
    font.bold: true
    padding: Style.space(6)
    focusPolicy: Qt.StrongFocus
    contentItem: Text {
      text: button.text
      textFormat: Text.PlainText
      font: button.font
      color: button.enabled ? Color.foreground : Color.muted
      horizontalAlignment: Text.AlignHCenter
      verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
      radius: Style.cornerRadius
      color: button.down ? Style.pressedFillFor(Color.foreground, Color.accent) :
        (button.hovered || button.checked ? Style.selectedFillFor(Color.foreground, Color.accent) : Style.hoverFillFor(Color.foreground, Color.accent))
      border.width: button.activeFocus ? 1 : 0
      border.color: Color.accent
    }
  }

  Popup {
    id: linkPopup
    modal: true
    focus: true
    width: Math.min(root.width - 20, 560)
    x: (root.width-width)/2
    y: 40
    background: Rectangle { color: Color.background; border.color: Color.accent }
    contentItem: ColumnLayout {
      Text { text: "Open GitHub link or owner/repository"; color: Color.foreground; font.family: Style.font.family }
      TextField { id: linkInput; Layout.fillWidth: true; placeholderText: "https://github.com/owner/repo/pull/123"; onAccepted: { root.openLink(text); linkPopup.close() } }
      Button { text: "Open in workspace"; onClicked: { root.openLink(linkInput.text); linkPopup.close() } }
    }
  }

  ColumnLayout {
    anchors.fill: parent
    anchors.margins: Style.space(8)
    spacing: Style.space(6)
    visible: root.item !== null

    RowLayout {
      Layout.fillWidth: true
      DeskButton { text: "← Back"; enabled: !root.posting; onClicked: root.goBack(); Accessible.name: "Back to previous view" }
      Item { Layout.fillWidth: true }
      Text { text: root.busy ? (root.posting ? "SENDING…" : "LOADING…") : ""; color: Color.accent; font.family: Style.font.family; font.pixelSize: Style.font.caption }
      DeskButton { text: "Refresh"; enabled: !root.busy; onClicked: root.refresh() }
    }

    Text {
      Layout.fillWidth: true
      text: root.detail ? root.detail.subtitle : (root.item ? root.item.repo : "")
      textFormat: Text.PlainText
      color: Color.accent
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      wrapMode: Text.WrapAnywhere
    }
    Text {
      Layout.fillWidth: true
      text: root.detail ? root.detail.title : (root.item ? root.item.title || "GitHub activity" : "")
      textFormat: Text.PlainText
      color: Color.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.subtitle
      font.bold: true
      maximumLineCount: 3
      elide: Text.ElideRight
      wrapMode: Text.Wrap
    }
    Text {
      Layout.fillWidth: true
      visible: text.length > 0
      text: root.error || root.notice
      textFormat: Text.PlainText
      color: root.error ? Color.urgent : Color.accent
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      wrapMode: Text.WrapAnywhere
    }
    Text {
      Layout.fillWidth: true
      visible: root.detail && !!root.detail.lifecycleStatus
      text: root.detail ? root.detail.lifecycleStatus || "" : ""
      textFormat: Text.PlainText
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      wrapMode: Text.Wrap
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(5)
      Repeater {
        id: tabButtons
        model: root.tabs
        delegate: DeskButton {
          required property var modelData
          required property int index
          drillControl: true
          text: modelData.label
          checked: root.activeTab && root.activeTab.id === modelData.id
          onClicked: root.selectTab(index)
        }
      }
    }

    Flow {
      Layout.fillWidth: true
      spacing: Style.space(5)
      DeskButton { text: "← Back"; enabled: !root.posting; onClicked: root.goBack() }
      DeskButton { text: "Repository"; visible: root.detail && !!root.detail.repositoryTarget; enabled: !root.busy; onClicked: root.showItem(root.detail.repositoryTarget, true) }
      DeskButton { text: "Pinned"; visible: root.item && root.item.kind === "collection" && root.item.collection === "repositories"; onClicked: root.showItem({kind:"collection",repo:"",collection:"pinned"},true) }
      DeskButton { text: "Recent"; visible: root.item && root.item.kind === "collection" && root.item.collection === "repositories"; onClicked: root.showItem({kind:"collection",repo:"",collection:"recent"},true) }
      DeskButton { text: "Previous page"; visible: root.detail && !!root.detail.previousTarget; enabled: !root.busy; onClicked: root.showItem(root.detail.previousTarget, false) }
      DeskButton { text: root.detail ? root.detail.nextLabel || "Next page" : "Next page"; visible: root.detail && !!root.detail.nextTarget; enabled: !root.busy; onClicked: root.showItem(root.detail.nextTarget, true) }
      DeskButton { text: "Open external reference"; visible: !!root.externalLink; onClicked: Qt.openUrlExternally(root.externalLink) }
    }
    Text {
      Layout.fillWidth: true
      visible: root.detail && !!root.detail.pageLabel
      text: root.detail ? root.detail.pageLabel || "" : ""
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }
    RowLayout {
      Layout.fillWidth: true
      TextField {
        id: findInput
        objectName: "readerFind"
        Layout.fillWidth: true
        placeholderText: "Find in this page, diff or log…"
        onTextChanged: { root.findText = text; root.findOffset = 0 }
        onAccepted: root.findNext()
      }
      DeskButton { text: "Find next"; onClicked: root.findNext() }
    }

    ScrollView {
      id: scroll
      objectName: "readerScroll"
      Layout.fillWidth: true
      Layout.fillHeight: true
      clip: true
      contentWidth: availableWidth
      ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
      ColumnLayout {
        width: scroll.availableWidth
        spacing: Style.space(8)
        Text {
          Layout.fillWidth: true
          visible: root.detail && root.detail.warnings.length > 0
          text: root.detail ? root.detail.warnings.join("\n") : ""
          textFormat: Text.PlainText
          color: Color.urgent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          wrapMode: Text.WrapAnywhere
        }
        TextEdit {
          objectName: "threadBody"
          Layout.fillWidth: true
          Layout.preferredHeight: contentHeight
          visible: root.detail && root.detail.body.length > 0
          text: root.detail ? root.detail.richBody || root.detail.body : ""
          textFormat: root.detail && root.detail.richBody ? TextEdit.RichText : TextEdit.PlainText
          onLinkActivated: function(link) { root.openLink(link) }
          readOnly: true
          activeFocusOnTab: false
          Keys.priority: Keys.BeforeItem
          Keys.onPressed: function(event) { root.handleKey(event) }
          selectByMouse: true
          wrapMode: TextEdit.WrapAnywhere
          color: Color.foreground
          selectionColor: Color.accent
          selectedTextColor: Color.background
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }
        Repeater {
          model: root.detail ? root.detail.images || [] : []
          delegate: ImagePreview { required property var modelData; entry: modelData }
        }
        Text {
          Layout.fillWidth: true
          visible: root.detail && root.activeTab && root.activeTab.blocks.length === 0
          text: "No " + (root.activeTab ? root.activeTab.label.toLowerCase() : "activity") + " yet."
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }
        Repeater {
          id: contentBlocks
          model: root.activeTab ? root.activeTab.blocks : []
          delegate: ColumnLayout {
            required property int index
            required property var modelData
            property alias drillButton: drillAction
            property alias bodyControl: blockText
            Layout.fillWidth: true
            spacing: Style.space(8)
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Color.muted; opacity: 0.25 }
            Text {
              Layout.fillWidth: true
              text: modelData.title
              textFormat: Text.PlainText
              color: Color.accent
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
              font.bold: true
              wrapMode: Text.WrapAnywhere
            }
            TextEdit {
              id: blockText
              Layout.fillWidth: true
              Layout.preferredHeight: contentHeight
              text: modelData.richBody || modelData.body
              textFormat: modelData.richBody ? TextEdit.RichText : TextEdit.PlainText
              onLinkActivated: function(link) { root.openLink(link) }
              readOnly: true
          activeFocusOnTab: false
          Keys.priority: Keys.BeforeItem
          Keys.onPressed: function(event) { root.handleKey(event) }
              selectByMouse: true
              wrapMode: TextEdit.WrapAnywhere
              color: Color.foreground
              selectionColor: Color.accent
              selectedTextColor: Color.background
              font.family: Style.font.family
              font.pixelSize: Style.font.body
            }
            Repeater {
              model: modelData.images || []
              delegate: ImagePreview { required property var modelData; entry: modelData }
            }
            DeskButton {
              id: drillAction
              drillControl: true
              visible: !!modelData.action || (modelData.operations || []).length > 0
              text: modelData.operationLabel || (modelData.action && modelData.action.kind === "job" ? "Read job logs" : "Inspect run")
              enabled: !root.posting
              onClicked: root.openBlock(index)
            }
            DeskButton {
              visible: !!modelData.action && (modelData.operations || []).length > 0 && !(root.detail && root.detail.cached)
              text: "Actions for this item…"
              enabled: !root.busy
              onClicked: actions.prepare(root.detail, modelData.operations)
            }
          }
        }
        DeskButton {
          visible: root.detail && root.activeTab && root.activeTab.id === "conversation" && !!(root.detail.nextPage || root.detail.nextCursor)
          text: "Load more comments"
          enabled: !root.busy
          onClicked: root.loadMore()
        }
      }
    }

    ColumnLayout {
      Layout.fillWidth: true
      visible: root.composing
      Text {
        Layout.fillWidth: true
        text: "Reply to " + (root.item ? root.item.repo : "") + (root.detail && root.detail.target.number ? " #" + root.detail.target.number : "")
        textFormat: Text.PlainText
        color: Color.accent
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }
      ScrollView {
        Layout.fillWidth: true
        Layout.preferredHeight: Style.space(110)
        TextArea {
          id: composer
          property bool keyboardControl: true
          Keys.priority: Keys.BeforeItem
          Keys.onPressed: function(event) { root.handleKey(event) }
          placeholderText: "Write a reply…"
          Accessible.name: "Reply text"
          textFormat: TextEdit.PlainText
          wrapMode: TextEdit.Wrap
          readOnly: root.posting
          selectByMouse: true
          color: Color.foreground
          placeholderTextColor: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          background: Rectangle { color: Color.background; border.color: composer.activeFocus ? Color.accent : Color.muted; radius: Style.cornerRadius }
          onTextChanged: if (root.draftKey) root.saveDraft()
        }
      }
      RowLayout {
        DeskButton {
          text: root.posting ? "Sending…" : "Post reply"
          enabled: !root.busy && composer.text.trim().length > 0 && composer.text.length <= 60000
          onClicked: root.submit("reply")
        }
        DeskButton { text: "Keep draft"; enabled: !root.posting; onClicked: { root.saveDraft(); root.composing = false; root.focusReader() } }
      }
    }
    Text {
      Layout.fillWidth: true
      text: root.composing ? "Tab: controls · Esc: keep draft · Enter: new line" : "↑ ↓: scroll/select · Enter/→: open · ←/Backspace: back · [ ]: tabs · C: reply · A: actions"
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      wrapMode: Text.Wrap
    }
    Flow {
      Layout.fillWidth: true
      spacing: Style.space(6)
      DeskButton {
        visible: root.detail && root.detail.canReply && !root.composing
        text: "Reply"
        enabled: !root.busy
        onClicked: root.startReply()
      }
      DeskButton {
        drillControl: true
        text: "Actions… (A)"
        enabled: !root.busy && !!root.detail && !root.detail.cached
        onClicked: root.openActions()
      }
      DeskButton {
        visible: root.detail && root.detail.threadId.length > 0
        text: "Mark as read"
        enabled: !root.busy
        onClicked: root.submit("mark-read")
      }
    }
  }
  Text {
    anchors.centerIn: parent
    visible: root.item === null
    text: "Select an item to read its thread."
    color: Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }
}
