import QtQuick
import QtQuick.Controls
import QtTest
import "../.." as Plugin

Item {
  id: host
  width: 960; height: 850
  // The dedicated runner supplies a monitored loopback HTTP endpoint.
  readonly property string pixelUrl: typeof testPixelUrl !== "undefined" ? testPixelUrl : "http://127.0.0.1:9/pixel.png"
  readonly property string hostile: '<img src="' + pixelUrl + '"> & <b>literal</b>'
  Plugin.ActionsDialog { id: dialog; parent: host }
  Component { id: imageProbe; Image {} }
  Component { id: previewComponent; Plugin.ImagePreview { width: 800 } }
  TestCase {
    name: "PlainTextChoices"
    when: windowShown
    SignalSpy { id: submissions; target: dialog; signalName: "submitted" }
    function init() { dialog.sending = false; dialog.close(); submissions.clear() }
    function cleanup() { dialog.sending = false; dialog.close() }
    function test_image_label_does_not_load_before_click() {
      var entry = typeof testImageEntry !== "undefined" ? testImageEntry : {label:host.hostile,url:host.pixelUrl.replace("pixel.png","preview.png")}
      var view = createTemporaryObject(previewComponent, host, {entry:entry})
      verify(view)
      var button = findChild(view, "loadImage")
      var preview = findChild(view, "previewImage")
      verify(button); verify(preview)
      wait(100)
      compare(button.contentItem.textFormat, Text.PlainText)
      compare(button.contentItem.text, "Load image: " + entry.label)
      compare(view.entry.label, host.hostile)
      verify(!view.loaded); compare(preview.source.toString(), "")
      if (typeof requestMonitor === "undefined") return
      compare(requestMonitor.paths().length, 0, "Creating a preview button must not request any image")
      mouseClick(button, button.width / 2, button.height / 2)
      tryCompare(preview, "status", Image.Ready)
      verify(view.loaded); compare(preview.source.toString(), entry.url)
      compare(button.contentItem.text, "Hide image")
      compare(JSON.stringify(requestMonitor.paths()), '["/preview.png"]')
      mouseClick(button, button.width / 2, button.height / 2)
      verify(!view.loaded); compare(preview.source.toString(), "")
      compare(button.contentItem.text, "Load image: " + entry.label)
      wait(100)
      compare(JSON.stringify(requestMonitor.paths()), '["/preview.png"]')
    }
    function test_network_monitor_positive_control() {
      if (typeof testPixelUrl === "undefined") skip("HTTP monitor is provided by tests/plaintext_runner.py")
      var probe = createTemporaryObject(imageProbe, host, {source: pixelUrl.replace("pixel.png", "control.png")})
      tryCompare(probe, "status", Image.Ready)
    }
    function test_external_choices_data() {
      return [{tag:"issue form",kind:"options",key:"form_0"},
              {tag:"workflow choice",kind:"options",key:"environment"},
              {tag:"suggestion",kind:"suggestions",key:"form_0"},
              {tag:"picker label",kind:"picker",key:"labels"}]
    }
    function test_external_choices(data) {
      var field = {key:data.key,label:"Choice",value:"",required:true}
      if (data.kind === "options") field.options = ["",host.hostile]
      if (data.kind === "suggestions") { field.suggestions = [host.hostile]; field.multiline = true }
      dialog.prepare({target:{repo:"example/repo",kind:"template"}},[
        {id:"create-template-issue",label:"Create issue",description:"Fixture",expected:{},fields:[field]}])
      dialog.choose(0)
      if (data.kind === "picker") {
        var choices = {}; choices[data.key] = {items:[{label:host.hostile,value:"original-value"}],page:1,more:false}
        dialog.candidates = choices
      }
      wait(20)
      var box = findChild(dialog.contentItem, data.kind + "_" + data.key)
      verify(box); verify(box.visible)
      box.forceActiveFocus()
      box.popup.open()
      tryCompare(box.popup, "opened", true)
      var list = box.popup.contentItem
      tryVerify(function() { return list.itemAtIndex(1) !== null })
      var option = list.itemAtIndex(1)
      compare(option.contentItem.textFormat, Text.PlainText)
      compare(option.contentItem.text, host.hostile)
      box.currentIndex = 1
      compare(box.currentText, host.hostile)
      compare(box.contentItem.textFormat, Text.PlainText)
      compare(box.contentItem.text, host.hostile)
      // Exercise the real delegate click and ComboBox activated handler.
      mouseClick(option, option.width / 2, option.height / 2)
      tryCompare(box.popup, "visible", false)
      var expected = data.kind === "picker" ? "original-value" : host.hostile
      compare(dialog.values[data.key], expected)
      dialog.review(); dialog.confirm()
      compare(submissions.count, 1)
      compare(submissions.signalArguments[0][0].values[data.key], expected)
      wait(100)
    }
  }
}
