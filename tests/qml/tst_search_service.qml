import QtQuick
import QtTest
import "../.." as Plugin
Item {
  Plugin.Service { id: service }
  TestCase {
    name: "SearchResponses"
    function result(ids,page,total) { return JSON.stringify({ok:true,items:ids.map(function(id){return {id:id}}),page:page,total:total,hasMore:page*50<total,warning:""}) }
    function init() { service.searchResults=[];service.searchError="";service.searchGeneration=10 }
    function test_stale_response_cannot_replace_new_search() {
      service.applySearch(result(["old"],1,1),9,false)
      compare(service.searchResults.length,0)
      service.applySearch(result(["new"],1,1),10,false)
      compare(service.searchResults[0].id,"new")
      service.applySearch(JSON.stringify({ok:false,error:"old failure"}),9,false)
      compare(service.searchError,"")
    }
    function test_append_deduplicates_and_failure_preserves_results() {
      service.applySearch(result(["a","b"],1,100),10,false)
      service.applySearch(result(["b","c"],2,100),10,true)
      compare(service.searchResults.length,3);compare(service.searchPage,2)
      service.applySearch(JSON.stringify({ok:false,error:"Rate limited"}),10,true)
      compare(service.searchResults.length,3);compare(service.searchError,"Rate limited")
    }
  }
}
