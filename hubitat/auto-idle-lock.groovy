/*
 * AutoIdleLock v1.0.0
 *
 */

definition(
    name: "AutoIdleLock",
    namespace: "zsimic",
    author: "Zoran Simic",
    description: "DO NOT INSTALL DIRECTLY, use the AutoIdle menu app",
    parent: "zsimic:AutoIdle",
    category: "Convenience",
    iconUrl: "",
    iconX2Url: "",
    iconX3Url: "",
    importUrl: "https://raw.githubusercontent.com/zsimic/home-server/master/hubitat/auto-idle-lock.groovy"
)

preferences {
    page(name: "pageMain")
}

def pageMain() {
    dynamicPage(name: "pageMain", title: "Automatic lock", install: true, uninstall: true) {
        section() {
            label title: "<b>Choose a name for this automation:</b>", required: true
            input "targetDevice", "capability.lock", title: "Select lock", multiple: false, required: true
            input "targetSensor", "capability.contactSensor", title: "Select sensor", multiple: false, required: true
            input "targetDuration", "number", title: "Number of minutes", multiple: false, required: true
        }
    }
}

def subscribeToEvents() {
    subscribe(targetDevice, "lock", eventHandler)
    subscribe(targetSensor, "contact", eventHandler)
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

def refreshDelay(md = 0) {
    unschedule(handleTarget)
    if (md == 0) { md = targetDuration * 60 }
    runIn(md, handleTarget)
}

def handleTarget() {
    if (targetSensor.currentValue("contact") == "closed") {
        targetDevice.lock()
    } else {
        refreshDelay()  // Sensor wasn't at right value, try again later
    }
}

def eventHandler(evt) {  // https://docs.smartthings.com/en/latest/ref-docs/event-ref.html
    if (evt.value == "locked") {
        unschedule(handleTarget)
    } else {
        refreshDelay()  // For any other event, simply refresh the delay
    }
}
