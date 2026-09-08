import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: root

  property var notifications: []
  property var issues: []
  property var pullRequests: []
  property var discussions: []
  property var ci: []
  property string viewer: ""
  property string fetchedAt: ""
  property string lastError: ""
  property string errorKind: ""
  property bool partial: false
  property bool stale: false
  property bool refreshing: false
  property bool refreshPending: false

  property var searchResults: []
  property var searchFilters: ({})
  property var searchPending: null
  property int searchGeneration: 0
  property int searchPage: 0
  property int searchTotal: 0
  property bool searchMore: false
  property string searchError: ""
  property string searchWarning: ""
  readonly property bool searching: searchProcess.running || searchPending !== null
  signal searchFinished(bool append, bool success)

  function search(filters, append) {
    if (append && (searching || !searchMore)) return
    if (!append) {
      searchGeneration++
      searchFilters = JSON.parse(JSON.stringify(filters))
      searchResults = []
      searchPage = 0; searchTotal = 0; searchMore = false
    }
    searchError = ""; searchWarning = ""
    searchPending = {request:Object.assign({}, searchFilters, {page:append ? searchPage + 1 : 1}), generation:searchGeneration, append:!!append}
    startSearch()
  }

  function startSearch() {
    if (searchProcess.running || !searchPending) return
    var next = searchPending
    searchPending = null
    searchProcess.request = next.request
    searchProcess.generation = next.generation
    searchProcess.append = next.append
    searchProcess.running = true
  }

  function applySearch(raw, generation, append) {
    if (generation !== searchGeneration) return
    try {
      var value = JSON.parse(raw)
      if (!value.ok) throw new Error(value.error || "Search failed")
      var result = append ? searchResults.slice() : []
      var ids = {}
      for (var i = 0; i < result.length; i++) ids[result[i].id] = true
      for (var j = 0; j < value.items.length; j++) if (!ids[value.items[j].id]) {
        result.push(value.items[j]); ids[value.items[j].id] = true
      }
      searchResults = result; searchPage = value.page; searchTotal = value.total
      searchMore = value.hasMore; searchWarning = value.warning || ""
      searchFinished(append, true)
    } catch (e) {
      searchError = String(e.message || e)
      searchFinished(append, false)
    }
  }

  Process {
    id: searchProcess
    property var request: ({})
    property int generation: 0
    property bool append: false
    command: ["python3", "-B", Qt.resolvedUrl("search_client.py").toString().replace(/^file:\/\//, "")]
    stdinEnabled: true
    onStarted: write(JSON.stringify(request) + "\n")
    stdout: StdioCollector { id: searchOutput; waitForEnd: true }
    stderr: StdioCollector { id: searchErrors; waitForEnd: true }
    onExited: function(code) {
      root.applySearch(searchOutput.text || JSON.stringify({ok:false,error:searchErrors.text || "Search did not return a response."}), generation, append)
      Qt.callLater(root.startSearch)
    }
  }

  readonly property string helperPath: Qt.resolvedUrl("github_client.py").toString().replace(/^file:\/\//, "")
  readonly property int attentionCount: notifications.length + issues.length + reviewRequestCount + failingCiCount
  readonly property int reviewRequestCount: countWhere(pullRequests, "lane", "Review requested")
  readonly property int failingCiCount: countWhere(ci, "state", "FAILURE") + countWhere(ci, "state", "ERROR")

  function countWhere(items, key, value) {
    var count = 0
    for (var i = 0; i < items.length; i++) if (String(items[i][key] || "") === value) count++
    return count
  }

  function refresh() {
    if (fetchProcess.running) {
      refreshPending = true
      return
    }
    if (helperPath === "/shell/plugins/panels/github/github_client.py") return
    refreshing = true
    lastError = ""
    fetchProcess.running = true
  }

  function applyResult(raw) {
    try {
      var parsed = JSON.parse(String(raw || ""))
      if (!parsed || parsed.ok !== true) {
        errorKind = String(parsed && parsed.errorKind || "fetch")
        lastError = String(parsed && parsed.error || "GitHub could not be refreshed")
        stale = parsed && parsed.stale === true
        return
      }
      viewer = String(parsed.viewer || "")
      notifications = Array.isArray(parsed.notifications) ? parsed.notifications : []
      issues = Array.isArray(parsed.issues) ? parsed.issues : []
      pullRequests = Array.isArray(parsed.pullRequests) ? parsed.pullRequests : []
      discussions = Array.isArray(parsed.discussions) ? parsed.discussions : []
      ci = Array.isArray(parsed.ci) ? parsed.ci : []
      fetchedAt = String(parsed.fetchedAt || "")
      partial = parsed.partial === true
      stale = parsed.stale === true
      errorKind = String(parsed.errorKind || "")
      lastError = String(parsed.error || "")
    } catch (error) {
      errorKind = "parse"
      lastError = "GitHub returned an unreadable response"
    }
  }

  Process {
    id: fetchProcess
    command: ["python3", "-B", root.helperPath]
    running: false
    stdout: StdioCollector {
      id: fetchStdout
      waitForEnd: true
    }
    stderr: StdioCollector {
      id: fetchStderr
      waitForEnd: true
    }
    onExited: function(exitCode) {
      root.refreshing = false
      if (fetchStdout.text) root.applyResult(fetchStdout.text)
      else {
        root.errorKind = "process"
        root.lastError = root.shortError(fetchStderr.text || "GitHub helper did not return data")
      }
      if (root.refreshPending) {
        root.refreshPending = false
        root.refresh()
      }
    }
  }

  function shortError(text) {
    var value = String(text || "").replace(/\s+/g, " ").trim()
    return value.length > 180 ? value.substring(0, 177) + "…" : value
  }

  Timer {
    interval: 180000
    repeat: true
    running: true
    onTriggered: root.refresh()
  }

  Component.onCompleted: refresh()
}
