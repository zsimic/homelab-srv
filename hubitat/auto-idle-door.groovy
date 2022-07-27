/*
 * AutoIdleDoor v1.0.0
 *
 */

definition(
    name: "AutoIdleDoor",
    namespace: "zsimic",
    author: "Zoran Simic",
    description: "DO NOT INSTALL DIRECTLY, use the AutoIdle menu app",
    parent: "zsimic:AutoIdle",
    category: "Convenience",
    iconUrl: "",
    iconX2Url: "",
    iconX3Url: "",
    importUrl: "https://raw.githubusercontent.com/zsimic/home-server/master/hubitat/auto-idle-door.groovy"
)

preferences {
    page(name: "pageMain")
}

def pageMain() {
    dynamicPage(name: "pageMain", title: "Automatic garage door close", install: true, uninstall: true) {
        section() {
            label title: "<b>Choose a name for this automation:</b>", required: true
            input "targetDevice", "capability.garageDoorControl", title: "Select door", multiple: false, required: true
            input "targetDuration", "number", title: "Number of minutes", multiple: false, required: true
        }
    }
}

def subscribeToEvents() {  // https://docs.smartthings.com/en/latest/capabilities-reference.html
    subscribe(targetDevice, "contact", eventHandler)
}

def installed() {
    subscribeToEvents()
}

def updated() {
    unsubscribe()
    unschedule()
    subscribeToEvents()
}

def uninstalled() {
    unsubscribe()
    unschedule()
}

def refreshDelay() {
    unschedule(handleTarget)
    runIn(targetDuration * 60, handleTarget)
}

def handleTarget() {
    targetDevice.close()
}

def eventHandler(evt) {  // https://docs.smartthings.com/en/latest/ref-docs/event-ref.html
    if (evt.value == "closed") {
        unschedule(handleTarget)
    } else if (evt.value == "open") {
        refreshDelay()
    }
}
