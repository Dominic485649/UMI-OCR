"""真实 GlobalConfigsPage + Configs 的延迟销毁快照回归；无窗口/内存配置。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[1]


def run(data, source):
    os.environ['QML_DISABLE_DISK_CACHE'] = '1'
    packages = data / 'site-packages'
    sys.path.insert(0, str(packages))
    handles = [os.add_dll_directory(str(packages / 'PySide6'))]
    from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer, QUrl, QCoreApplication, QEvent, QtMsgType, qInstallMessageHandler
    from PySide6.QtGui import QGuiApplication, QColor
    from PySide6.QtQml import QQmlEngine, QQmlComponent, QQmlExpression
    from PySide6.QtQuickControls2 import QQuickStyle
    QQuickStyle.setStyle('Basic')
    app = QGuiApplication(['sidebar-regression-windowless'])
    engine = QQmlEngine()
    engine.addImportPath(str(packages / 'PySide6/qml'))
    qml = source / 'qt_res/qml'
    errors, samples, signals = [], [], []
    class Settings(QObject):
        @Slot(str, str, result=bool)
        def contains(self, *_args): return False
        @Slot(str, str, 'QVariant', result='QVariant')
        def value(self, _category, _key, default): return default
        @Slot(str, str, 'QVariant')
        def setValue(self, *_args): raise AssertionError('此回归不得写入配置')
        @Slot()
        def sync(self): pass
    class Bus(QObject):
        @Slot(str, 'QVariant', str, str)
        def subscribeGroup(self, *_args): pass
        @Slot(str)
        def unsubscribeGroup(self, *_args): pass
    class Popup(QObject):
        @Slot(str, str, str)
        def messageMemory(self, *_args): pass
    class App(QObject):
        effectsChanged = Signal()
        @Property(QObject, constant=True)
        def globalConfigs(self): return self.shared
        @Property(QObject, constant=True)
        def pubSub(self): return self.bus
        @Property(QObject, constant=True)
        def popup(self): return self.popup_stub
        @Property(bool, notify=effectsChanged)
        def enabledEffect(self): return getattr(self, '_effects', False)
        @enabledEffect.setter
        def enabledEffect(self, value):
            self._effects = bool(value)
            self.effectsChanged.emit()
    stub = App()
    stub.bus, stub.popup_stub = Bus(stub), Popup(stub)
    settings = Settings()
    context = engine.rootContext()
    context.setContextProperty('UmiSettings', settings)
    context.setContextProperty('qmlapp', stub)
    context.setContextProperty('theme', {**{name: QColor(value) for name, value in {
        'bgColor':'#ffffff', 'textColor':'#111111', 'subTextColor':'#555555', 'noColor':'#bb3322',
        'yesColor':'#228844', 'specialBgColor':'#eeeeee', 'specialTextColor':'#1166cc',
        'coverColor1':'#11000000', 'coverColor2':'#22000000', 'coverColor3':'#33000000', 'coverColor4':'#55000000',
    }.items()}, 'fontFamily':'Microsoft YaHei', 'dataFontFamily':'Microsoft YaHei'})
    context.setContextProperty('size_', {'scale':1,'line':20,'smallLine':16,'largeLine':24,
        'text':14,'smallText':12,'largeText':18,'spacing':8,'smallSpacing':4,
        'btnRadius':4,'panelRadius':6,'baseRadius':4})
    previous = qInstallMessageHandler(lambda kind, _context, text: errors.append((kind, text)))
    config = QQmlComponent(engine)
    config.setData(('import QtQuick 2.15\nimport "' + QUrl.fromLocalFile(str(qml / 'Configs')).toString() + '''"
Configs {
    autoLoad:false; lazyPanel:true; category_:"SidebarTest"
    property var fontPanel
    // 此测试只覆盖活动导航，模型来源生命周期由独立中心测试覆盖。
    property var ocrManager: ({ensureTaskSources:function(){}})
    property var followupDefinition:null
    width:720; height:480
    function applyReloadChain(first, second) {
        followupDefinition = second
        configDict = first
        reload()
    }
    function applyFollowup() {
        const next = followupDefinition
        followupDefinition = null
        configDict = next
        reload()
    }
    onConfigurationReloaded: {
        if(followupDefinition !== null) Qt.callLater(applyFollowup)
    }
}''').encode(), QUrl.fromLocalFile(str(qml / 'sidebar-test.qml')))
    shared = config.create()
    assert shared is not None, config.errorString()
    stub.shared = shared
    engine.globalObject().setProperty('shared', engine.newQObject(shared))
    def js(code, obj=shared):
        expression = QQmlExpression(QQmlEngine.contextForObject(obj), obj, code)
        value = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        if isinstance(value, tuple): value = value[0]
        return value.toVariant() if hasattr(value, 'toVariant') else value
    def jjson(code, obj=shared): return json.loads(js('JSON.stringify(' + code + ')', obj))
    expected_by_title, expected_keys_by_title = {}, {}
    def definition(label, reverse=False):
        groups = {'ui':{'type':'group','title':label + '-ui','fontFamily':{'default':'Microsoft YaHei'},
                        'dataFontFamily':{'default':'Microsoft YaHei'},
                        'nested':{'type':'group','title':label + '-nested'}},
                  'advancedGroup':{'type':'group','title':label + '-advanced','advanced':True},
                  'plugins':{'type':'group','title':label + '-plugins'}}
        if reverse:
            groups = dict(reversed(list(groups.items())))
        expected_by_title[groups['ui']['title']] = [
            {'title':('* ' if group.get('advanced') else '') + group['title'],
             'advanced':bool(group.get('advanced'))} for group in groups.values()]
        expected_keys_by_title[groups['ui']['title']] = list(groups)
        return groups
    js('configDict=' + json.dumps(definition('initial')) + ';reload()')
    cold = {'panelBuilt':bool(shared.property('panelBuilt')),
            'groups':jjson('panelComponent.getGroupList() || null'),
            'control_count':js('Object.keys(compDict).length')}
    assert not cold['panelBuilt'] and cold['control_count'] == 0 and cold['groups'] in (None, []), cold
    page_component = QQmlComponent(engine, QUrl.fromLocalFile(str(qml / 'TabPages/GlobalConfigsPage/GlobalConfigsPage.qml')))
    page = page_component.createWithInitialProperties({'width':960,'height':640})
    assert page is not None, page_component.errorString()
    assert not shared.property('panelBuilt'), '创建标签对象不能提前建全局panel'
    page.showPage.emit()
    panel_object = js('panelComponent')
    started = time.monotonic()
    def observe(label):
        left = jjson('groupList', page)
        panel = jjson('panelComponent.getGroupList()')
        raw = jjson('(function(){var c=panelContainer.children,a=[];for(var i=0;i<c.length;i++)'
                    'if(c[i].title!==undefined)a.push({title:c[i].title,advanced:c[i].advanced});return a})()', panel_object)
        current_title = js('configDict.ui.title')
        expected = expected_by_title[current_title]
        registry = jjson('configs.compList.map(function(c){return {key:c.key,root:c.parent===panelContainer}})', panel_object)
        active_keys = [item['key'] for item in registry if item['root']]
        buttons = []
        root = js('leftTop', page)
        pending = list(root.childItems())
        while pending:
            item = pending.pop(0)
            if item.metaObject().indexOfProperty('text_') >= 0 and item.metaObject().indexOfProperty('bgPressColor_') >= 0:
                buttons.append({'text':str(item.property('text_')),'visible':bool(item.property('visible'))})
            pending.extend(item.childItems())
        advanced = bool(shared.property('advanced'))
        return {'label':label,'ms':round((time.monotonic()-started)*1000,2),
                'revision':shared.property('definitionRevision'),'left':left,'panel':panel,'buttons':buttons,
                'expected':expected,'raw_visual_groups':raw,'old_and_new_coexist':len(raw)>len(expected),
                'registry_keys':[item['key'] for item in registry],'active_registry_keys':active_keys,
                'registry_matches_layout':active_keys == expected_keys_by_title[current_title],
                'panel_is_current':panel == expected,'equal':left == panel,
                'buttons_equal':[button['text'] for button in buttons] == [group['title'] for group in expected],
                'visibility_equal':[button['visible'] for button in buttons] ==
                    [not group['advanced'] or advanced for group in expected]}
    def navigation_probe():
        container = js('panelContainer', panel_object)
        registry = shared.property('compList')
        registry = registry.toVariant() if hasattr(registry, 'toVariant') else registry
        active = [item for item in registry if item.property('parent') == container]
        raw = [item for item in container.childItems() if item.metaObject().indexOfProperty('title') >= 0]
        probes = []
        stub.enabledEffect = True
        try:
            for index, target in enumerate(active):
                for item in raw:
                    js('blinkAnimation.stop()', item)
                js('panelComponent.scrollToGroup(' + str(index) + ')')
                hits = [item for item in raw if js('blinkAnimation.running', item)]
                probes.append({'index':index,'expected_key':target.property('key'),
                    'expected_title':target.property('title'),'hit_keys':[item.property('key') for item in hits],
                    'hit_titles':[item.property('title') for item in hits],
                    'hit_is_exact_current_object':len(hits) == 1 and hits[0] == target})
        finally:
            for item in raw:
                js('blinkAnimation.stop()', item)
            stub.enabledEffect = False
        return probes
    signal_callbacks, signal_errors = [], []
    for name in ('panelRebuilt','configurationReloaded'):
        def callback(kind=name):
            try:
                sample = observe(kind)
                sample['navigation'] = navigation_probe() if kind == 'panelRebuilt' else []
                signals.append(sample)
            except Exception as exc:
                signal_errors.append(repr(exc))
        getattr(shared,name).connect(callback)
        signal_callbacks.append(callback)
    failure = []
    labels = iter(('zh_TW','zh_CN','en_US','virtual-layout'))
    def change():
        try:
            label = next(labels)
        except StopIteration:
            app.quit()
            return
        first, second = definition(label + '-first'), definition(label + '-followup', reverse=True)
        if label == 'virtual-layout':
            layout = [{'key':'plugins'},
                {'key':'virtual.display.group','origin':{'type':'group','title':'Virtual Display'},
                 'items':[{'key':'nestedWithoutDot','origin':{'type':'group','title':'Nested No Dot'},'items':[]},
                          {'key':'ui'}]},
                {'key':'advanced.synthetic.group','origin':{'type':'group','title':'Virtual Advanced','advanced':True},'items':[]}]
            for groups in (first, second):
                expected_by_title[groups['ui']['title']] = [
                    {'title':groups['plugins']['title'],'advanced':False},
                    {'title':'Virtual Display','advanced':False},
                    {'title':'* Virtual Advanced','advanced':True}]
                expected_keys_by_title[groups['ui']['title']] = [item['key'] for item in layout]
            js('isChangedInit=false;panelLayout=' + json.dumps(layout))
        signal_start = len(signals)
        js('applyReloadChain(' + json.dumps(first) + ',' + json.dumps(second) + ')')
        def verify():
            try:
                sample = observe(label)
                samples.append(sample)
                chain = signals[signal_start:]
                assert not signal_errors, signal_errors
                assert [event['label'] for event in chain] == [
                    'panelRebuilt','configurationReloaded','panelRebuilt','configurationReloaded'], chain
                assert all(event['old_and_new_coexist'] for event in chain), '必须实测旧新children仍共存'
                assert all(event['panel_is_current'] and event['equal'] and event['registry_matches_layout'] for event in chain), {
                    'reason':'同步双信号链必须只枚举当前活动分组，不能依赖下一帧销毁', 'chain':chain}
                assert all(len(event['navigation']) == len(event['expected']) for event in chain if event['label'] == 'panelRebuilt'), chain
                assert all(probe['hit_is_exact_current_object'] for event in chain for probe in event['navigation']), chain
                if label == 'virtual-layout':
                    assert 'virtual.display.group' in sample['active_registry_keys'] and 'advanced.synthetic.group' in sample['active_registry_keys'], sample
                    assert 'nestedWithoutDot' in sample['registry_keys'] and 'nestedWithoutDot' not in sample['active_registry_keys'], sample
                    assert all(key not in js('getValueDict()') for key in ('virtual.display.group','advanced.synthetic.group','nestedWithoutDot')), '虚拟展示组不能成为持久化键'
                assert sample['panel_is_current'] and sample['equal'] and sample['buttons_equal'] and sample['visibility_equal'], sample
                assert len(sample['left']) == 3 and all('nested' not in group['title'] for group in sample['left']), sample
                js('advanced=true')
                expanded = observe(label + '-advanced-expanded')
                samples.append(expanded)
                assert expanded['visibility_equal'] and expanded['panel'] == sample['panel'], expanded
                js('advanced=false')
                assert not app.allWindows(), '此回归不能创建QWindow'
            except Exception as exc:
                failure.append(str(exc))
                app.quit()
                return
            QTimer.singleShot(0, change)
        QTimer.singleShot(30, verify)
    QTimer.singleShot(30, change)
    app.exec()
    warnings = [text for kind, text in errors if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)]
    if warnings: failure.append('QML warnings: ' + repr(warnings))
    sources = [Path(__file__), qml / 'Configs/Configs.qml', qml / 'TabPages/GlobalConfigsPage/GlobalConfigsPage.qml']
    report = {'mode':'real-qml-sidebar-windowless-regression','python':sys.version,
        'runtime':str(data),'source_root':str(source),'passed':not failure,'failures':failure,
        'cold_state':cold,'signal_errors':signal_errors,'synchronous_signal_samples':signals,'settled_samples':samples,'qwindow_count':len(app.allWindows()),
        'settings':'memory-only/no-write','source_sha256':{str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
        'limits':'不替代fresh候选真实七语/窗口/插件联合验收；标题为回归标记，不是翻译表验收'}
    page.deleteLater()
    shared.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qInstallMessageHandler(previous)
    del handles
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data_root', type=Path)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), '不得覆盖旧证据'
    report = run(args.data_root.resolve(), args.source_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'passed':report['passed'],'failure_count':len(report['failures']),
        'signals':[{'kind':item['label'],'revision':item['revision'],'raw':len(item['raw_visual_groups']),
                    'panel':len(item['panel']),'current':item['panel_is_current'],'left_equal':item['equal'],
                    'navigation_count':len(item['navigation']),
                    'navigation_ok':all(probe['hit_is_exact_current_object'] for probe in item['navigation'])}
                   for item in report['synchronous_signal_samples']],
        'settled_samples':[{'label':item['label'],'panel_is_current':item['panel_is_current'],
                           'buttons_equal':item['buttons_equal'],'visibility_equal':item['visibility_equal']}
                          for item in report['settled_samples']],'output':str(args.output)}, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
