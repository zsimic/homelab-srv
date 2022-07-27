/*
 * AutoIdle v1.0.0
 *
 */

public static String version() { return "v1.0.0" }

definition(
    name: "AutoIdle",
    namespace: "zsimic",
    author: "Zoran Simic",
    description: "Auto close/lock a door, or turn off a light after N minutes",
    singleInstance: true,
    installOnOpen: true,
    category: "Convenience",
    iconUrl: "",
    iconX2Url: "",
    iconX3Url: "",
    importUrl: "https://raw.githubusercontent.com/zsimic/home-server/master/hubitat/auto-idle.groovy"
)

preferences {
    page(name: "pageMain")
}

def pageMain() {
    dynamicPage(name: "pageMain", title: "Auto door lock/close, or lights off", install: true, uninstall: true) {
        section() {
            paragraph "Automatically lock or close a door, or turn lights off after N minutes"
        }
        section() {
            app(name: "autoclose", title: "Automatically close a garage door", appName: "AutoIdleDoor", namespace: "zsimic", multiple: true, uninstall: true)
        }
        section() {
            app(name: "autolock", title: "Automatically lock a door", appName: "AutoIdleLock", namespace: "zsimic", multiple: true, uninstall: true)
        }
        section() {
            app(name: "autooff", title: "Automatically turn off lights", appName: "AutoIdleLights", namespace: "zsimic", multiple: true, uninstall: true)
        }
    }
}

def installed() {
}

def updated() {
}
