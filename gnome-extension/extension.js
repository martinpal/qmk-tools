import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

// D-Bus interface XML
const QMKLayerInterface = `
<node>
  <interface name="com.qmk.LayerIndicator">
    <method name="SetLayer">
      <arg type="s" direction="in" name="layerName"/>
      <arg type="s" direction="in" name="layerColor"/>
    </method>
    <method name="GetLayer">
      <arg type="s" direction="out" name="layerName"/>
      <arg type="s" direction="out" name="layerColor"/>
    </method>
  </interface>
</node>`;

class QMKLayerIndicator {
    constructor() {
        this._layerName = 'Base';
        this._layerColor = '#787878';  // Default gray

        // Create the button for the top bar
        this._button = new St.Button({
            style_class: 'panel-button',
            reactive: false,
            can_focus: false,
            track_hover: false,
            y_align: Clutter.ActorAlign.CENTER,
        });

        // Create label
        this._label = new St.Label({
            text: this._layerName,
            y_align: Clutter.ActorAlign.CENTER,
            style: 'font-weight: bold;',
        });

        this._button.set_child(this._label);
        this._updateStyle();

        // Add to top bar (left side, after workspace indicator)
        // Insert at index 1 to place after the workspace indicator
        Main.panel._leftBox.insert_child_at_index(this._button, 1);

        // Setup D-Bus interface
        this._setupDBus();
    }

    _setupDBus() {
        try {
            // Export the D-Bus interface
            const ifaceXml = Gio.DBusNodeInfo.new_for_xml(QMKLayerInterface).interfaces[0];

            this._dbusImpl = Gio.DBusExportedObject.wrapJSObject(ifaceXml, this);
            this._dbusImpl.export(Gio.DBus.session, '/com/qmk/LayerIndicator');

            // Request the bus name
            Gio.DBus.session.own_name(
                'com.qmk.LayerIndicator',
                Gio.BusNameOwnerFlags.NONE,
                null,
                null
            );
        } catch (e) {
            // Silently fail - extension still works without D-Bus
        }
    }

    _updateStyle() {
        // Set background color based on layer
        // Fixed width, rounded corners with radius = half of height
        const style = `
            background-color: ${this._layerColor};
            color: black;
            padding: 0 12px;
            border-radius: 12px;
            margin: 2px 4px;
            font-weight: bold;
            text-shadow: 1px 1px 2px rgba(255, 255, 255, 0.3);
            min-width: 80px;
            max-width: 80px;
            text-align: center;
        `;
        this._button.set_style(style);
    }

    // D-Bus method: SetLayer
    SetLayer(layerName, layerColor) {
        this._layerName = layerName;
        this._layerColor = layerColor;
        this._label.set_text(layerName);
        this._updateStyle();
    }

    // D-Bus method: GetLayer
    GetLayer() {
        return [this._layerName, this._layerColor];
    }

    destroy() {
        if (this._dbusImpl) {
            this._dbusImpl.unexport();
            this._dbusImpl = null;
        }

        if (this._button) {
            this._button.destroy();
            this._button = null;
        }
    }
}

export default class QMKLayerIndicatorExtension extends Extension {
    enable() {
        this._indicator = new QMKLayerIndicator();
    }

    disable() {
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
    }
}
