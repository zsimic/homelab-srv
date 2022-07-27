/*
 * AutoIdleLights v1.0.0
 *
 */

definition(
    name: "AutoIdleLights",
    namespace: "zsimic",
    author: "Zoran Simic",
    description: "DO NOT INSTALL DIRECTLY, use the AutoIdle menu app",
    parent: "zsimic:AutoIdle",
    category: "Convenience",
    iconUrl: "",
    iconX2Url: "",
    iconX3Url: "",
    importUrl: "https://raw.githubusercontent.com/zsimic/home-server/master/hubitat/auto-idle-lights.groovy"
)

preferences {
    page(name: "pageMain")
}

def pageMain() {
    dynamicPage(name: "pageMain", title: "Automatic lights off", install: true, uninstall: true) {
        section() {
            label title: "<b>Choose a name for this automation:</b>", required: true
            input "targetDevice", "capability.switch", title: "Select lights", multiple: true, required: true
            input "targetDuration", "decimal", title: "Number of hours", multiple: false, required: true
        }
    }
}

def subscribeToEvents() {
    def ids = targetDevice.collect { entry -> entry.displayName }
    def removed = state.findAll { !ids.contains(it.key) }
    for (entry in removed) {
        state.remove(entry.key)
    }
    unsubscribe()
    subscribe(targetDevice, "switch", eventHandler)
    refreshDelay()
}

def installed() {
    subscribeToEvents()
}

def updated() {
    unschedule()
    subscribeToEvents()
}

def uninstalled() {
    state.clear()
    unsubscribe()
    unschedule()
}

def refreshDelay() {
    unschedule(handleTarget)
    if (state) {
        runIn(300, checkLights)  // Check every 5 minutes
    }
}

def checkLights() {
    def current = now()
    for (d in targetDevice) {
        def devid = d.displayName
        if (state.containsKey(devid)) {
            if (state[devid] < current) {
                d.off()
                state.remove(devid)
            }
        }
    }
    refreshDelay()
}

def eventHandler(evt) {  // https://docs.smartthings.com/en/latest/ref-docs/event-ref.html
    def devid = evt.displayName
    if (evt.value == "off") {
        state.remove(devid)
    } else {
        state[devid] = now() + 3600000 * targetDuration
    }
    refreshDelay()
}
