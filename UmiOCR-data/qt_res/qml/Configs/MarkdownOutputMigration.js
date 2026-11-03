.pragma library

function migrate(configs, settings) {
    // 初始绑定可能先触发空 schema 的 reload；此时不能提前标记迁移完成。
    if(!configs.originDict["mission.filesType.md"]) return
    const category = configs.category_
    const marker = "mission.markdownFormatVersion"
    if(Number(settings.value(category, marker, 0)) >= 1) return
    function selected(key) {
        const value = settings.value(category, "mission.filesType." + key, false)
        return value === true || value === "true"
    }
    const hadLegacy = ["txt", "txtPlain", "txtIndividual"].some(key => settings.contains(category, "mission.filesType." + key))
    if(!hadLegacy) return
    if(selected("txt") || selected("txtPlain")) configs.setValue("mission.filesType.md", true, true)
    if(selected("txtIndividual") && configs.originDict["mission.filesType.mdIndividual"])
        configs.setValue("mission.filesType.mdIndividual", true, true)
    // 先持久化迁移后的值再记录完成标记，避免退出发生在缓存计时器之前。
    configs.flushCache()
    settings.setValue(category, marker, 1)
}
