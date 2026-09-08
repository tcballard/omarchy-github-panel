import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import qs.Commons

ColumnLayout {
  id: root
  property bool busy: false
  property alias query: queryField.text
  property alias repository: repoField.text
  readonly property bool containsFocus: queryField.activeFocus || repoField.activeFocus || typeFilter.activeFocus || stateFilter.activeFocus || searchButton.activeFocus
  signal submitted(var filters)
  signal resultsRequested()
  spacing: Style.space(6)
  function focusQuery() { queryField.forceActiveFocus(); queryField.selectAll() }
  function runSearch() {
    submitted({query:queryField.text, repo:repoField.text,
      kind:["all","issue","pr"][typeFilter.currentIndex], state:["all","open","closed","merged"][stateFilter.currentIndex]})
  }
  function handleEscape(event) {
    if (event.key === Qt.Key_Escape) { root.resultsRequested(); event.accepted = true }
  }
  component Field: TextField {
    id: field
    color: Color.foreground
    placeholderTextColor: Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    padding: Style.space(8)
    selectByMouse: true
    background: Rectangle { color: Color.background; border.color: field.activeFocus ? Color.accent : Color.muted; radius: Style.cornerRadius }
    Keys.onPressed: function(event) {
      if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) { if (!event.isAutoRepeat) root.runSearch(); event.accepted = true }
      else if (event.key === Qt.Key_Escape || event.key === Qt.Key_Down) { root.resultsRequested(); event.accepted = true }
    }
  }
  RowLayout {
    Layout.fillWidth: true
    Field {
      id: queryField
      objectName: "searchQuery"
      Layout.fillWidth: true
      placeholderText: "Search GitHub — text or qualifiers such as assignee:@me"
      Accessible.name: "GitHub search query"
    }
    Button {
      id: searchButton
      text: root.busy ? "Searching…" : "Search"
      onClicked: root.runSearch()
      Keys.onPressed: function(event) {
        root.handleEscape(event)
        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) { if (!event.isAutoRepeat) root.runSearch(); event.accepted = true }
      }
    }
  }
  RowLayout {
    Layout.fillWidth: true
    Field {
      id: repoField
      objectName: "searchRepository"
      Layout.fillWidth: true
      placeholderText: "Repository (optional): owner/name"
      Accessible.name: "Repository filter"
    }
    ComboBox {
      id: typeFilter
      objectName: "searchType"
      model: ["Issues + PRs", "Issues", "PRs"]
      Accessible.name: "Item type"
      Keys.onPressed: function(event) { root.handleEscape(event) }
    }
    ComboBox {
      id: stateFilter
      objectName: "searchState"
      model: ["Any state", "Open", "Closed", "Merged"]
      Accessible.name: "Item state"
      Keys.onPressed: function(event) { root.handleEscape(event) }
    }
  }
}
