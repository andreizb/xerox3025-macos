// SPDX-License-Identifier: MIT
// Build-time helper: public Automator APIs serialize Apple's own action format.
import Foundation
import Automator

@main struct WorkflowBuilder {
    static func main() throws {
        let args = CommandLine.arguments
        guard args.count == 4 else { throw NSError(domain: "WorkflowBuilder", code: 1, userInfo: [NSLocalizedDescriptionKey: "workflow-builder SCRIPT_FILE OUTPUT.workflow true|false (open in Preview)"]) }
        let script = try String(contentsOfFile: args[1], encoding: .utf8)
        let workflow = AMWorkflow()
        let action = try AMBundleAction(contentsOf: URL(fileURLWithPath: "/System/Library/Automator/Run Shell Script.action"))
        action.parameters = NSMutableDictionary(dictionary: ["shell": "/bin/bash", "inputMethod": 1,
            "source": script, "COMMAND_STRING": script, "CheckedForUserDefaultShell": true])
        workflow.addAction(action)
        if args[3] == "true" {
            let open = try AMBundleAction(contentsOf: URL(fileURLWithPath: "/System/Library/Automator/Open Finder Items.action"))
            open.parameters = NSMutableDictionary(dictionary: ["appPath": "/System/Applications/Preview.app"])
            workflow.addAction(open)
        }
        try workflow.write(to: URL(fileURLWithPath: args[2]))
        print("Saved using AMWorkflow.write: \(args[2])")
    }
}
