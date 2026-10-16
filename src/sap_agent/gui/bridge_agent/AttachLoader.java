package sap_agent.gui.bridge_agent;

import com.sun.tools.attach.VirtualMachine;

public class AttachLoader {
    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("Usage: AttachLoader <pid> <agentJarPath>");
            System.exit(1);
        }
        String pid = args[0];
        String jarPath = args[1];
        System.out.println("[AttachLoader] Attaching to PID " + pid + " with " + jarPath);
        VirtualMachine vm = VirtualMachine.attach(pid);
        try {
            vm.loadAgent(jarPath, "init");
        } catch (com.sun.tools.attach.AgentInitializationException e) {
            if (e.returnValue() != 0) {
                System.err.println("[AttachLoader] AgentInitializationException return value = " + e.returnValue());
                throw e;
            }
        }
        vm.detach();
        System.out.println("[AttachLoader] Agent loaded successfully!");
    }
}
