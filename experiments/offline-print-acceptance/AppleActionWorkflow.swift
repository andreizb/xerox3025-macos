// SPDX-License-Identifier: MIT
// Serialize only existing Apple actions with public Automator APIs.
import Foundation
import Automator

@main struct AppleActionWorkflow {
    static func main() throws {
        let args=CommandLine.arguments
        guard args.count==3 else { throw NSError(domain:"OfflineAppleAction",code:64) }
        let data=try Data(contentsOf:URL(fileURLWithPath:args[1]))
        guard let entries=try JSONSerialization.jsonObject(with:data) as? [[String:Any]] else {
            throw NSError(domain:"OfflineAppleAction",code:65)
        }
        let allowed:Set<String>=["Watermark PDF Documents","Rename Finder Items","Copy Finder Items","Move Finder Items"]
        let workflow=AMWorkflow()
        for entry in entries {
            guard let name=entry["action"] as? String,allowed.contains(name),
                  let supplied=entry["parameters"] as? [String:Any] else {
                throw NSError(domain:"OfflineAppleAction",code:66)
            }
            let path="/System/Library/Automator/\(name).action"
            let action=try AMBundleAction(contentsOf:URL(fileURLWithPath:path))
            let params=NSMutableDictionary(dictionary:action.parameters as? [String:Any] ?? [:])
            params.addEntries(from:supplied)
            action.parameters=params
            workflow.addAction(action)
        }
        try workflow.write(to:URL(fileURLWithPath:args[2]))
    }
}
