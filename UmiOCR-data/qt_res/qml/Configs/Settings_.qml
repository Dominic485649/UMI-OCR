// ==============================================================
// =============== 对Settings的封装，提供本地化保存 ===============
// ==============================================================

import QtQml 2.15

QtObject {
    property string category: ""

    function value(key, defaultValue) {
        if(!UmiSettings.contains(category, key))
            return defaultValue
        return UmiSettings.value(category, key, defaultValue)
    }

    function readValue(key, defaultValue) {
        return value(key, defaultValue)
    }

    function setValue(key, newValue) {
        UmiSettings.setValue(category, key, newValue)
    }

    function writeValue(key, newValue) {
        setValue(key, newValue)
    }

    function remove(key) {
        UmiSettings.remove(category, key)
    }

    function sync() {
        UmiSettings.sync()
    }
}
