# -*- coding: utf-8 -*-
#
# Copyright (C) 2014 GNS3 Technologies Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
VPCS device implementation.
"""

import os
from functools import partial
from gns3.node import Node
from gns3.ports.port import Port
from gns3.ports.ethernet_port import EthernetPort
from gns3.utils.normalize_filename import normalize_filename

import logging
log = logging.getLogger(__name__)


class VPCSDevice(Node):

    """
    VPCS device.

    :param module: parent module for this node
    :param server: GNS3 server instance
    :param project: Project instance
    """

    def __init__(self, module, server, project):
        Node.__init__(self, server)

        log.info("VPCS instance is being created")
        self._project = project
        self._vm_id = None
        self._defaults = {}
        self._inital_settings = None
        self._export_directory = None
        self._loading = False
        self._module = module
        self._ports = []
        self._settings = {"name": "",
                          "script_file": "",
                          "startup_script": None,
                          "console": None}

        port_name = EthernetPort.longNameType() + str(0)
        short_name = EthernetPort.shortNameType() + str(0)

        # VPCS devices have only one Ethernet port
        port = EthernetPort(port_name)
        port.setShortName(short_name)
        port.setPortNumber(0)
        self._ports.append(port)
        log.debug("port {} has been added".format(port_name))

        # save the default settings
        self._defaults = self._settings.copy()

    def setup(self, name=None, vm_id=None, additional_settings={}):
        """
        Setups this VPCS device.

        :param name: optional name
        :param vm_id: VM identifier
        :param additional_settings: additional settings for this device
        """

        # let's create a unique name if none has been chosen
        if not name:
            name = self.allocateName("PC")

        if not name:
            self.error_signal.emit(self.id(), "could not allocate a name for this VPCS device")
            return

        params = {"name": name,
                  "project_id": self._project.id()}

        if vm_id:
            params["vm_id"] = vm_id

        if "script_file" in additional_settings:
            try:
                with open(additional_settings["script_file"]) as f:
                    additional_settings["startup_script"] = f.read()
            except (OSError) as e:
                log.error("Could not load the script file to {}".format(additional_settings["script_file"], e))
            del additional_settings["script_file"]

        # If we have an vm id that mean the VM already exits and we should not send startup_script
        if "startup_script" in additional_settings and vm_id is not None:
            del additional_settings["startup_script"]

        params.update(additional_settings)
        self._server.post("/vpcs/vms", self._setupCallback, body=params)

    def _setupCallback(self, result, error=False):
        """
        Callback for setup.

        :param result: server response (dict)
        :param error: indicates an error (boolean)
        """

        if error:
            log.error("error while setting up {}: {}".format(self.name(), result["message"]))
            self.server_error_signal.emit(self.id(), result["message"])
            return

        self._vm_id = result["vm_id"]
        # update the settings using the defaults sent by the server
        for name, value in result.items():
            if name in self._settings and self._settings[name] != value:
                log.info("VPCS instance setting up and updating {} from '{}' to '{}'".format(name, self._settings[name], value))
                self._settings[name] = value

        if self._loading:
            self.updated_signal.emit()
        else:
            self.setInitialized(True)
            log.info("VPCS instance {} has been created".format(self.name()))
            self.created_signal.emit(self.id())
            self._module.addNode(self)

    def delete(self):
        """
        Deletes this VPCS instance.
        """

        log.debug("VPCS device {} is being deleted".format(self.name()))
        # first delete all the links attached to this node
        self.delete_links_signal.emit()
        if self._vm_id:
            self._server.delete("/vpcs/vms/{vm_id}".format(vm_id=self._vm_id), self._deleteCallback)
        else:
            self.deleted_signal.emit()
            self._module.removeNode(self)

    def _deleteCallback(self, result, error=False):
        """
        Callback for delete.

        :param result: server response (dict)
        :param error: indicates an error (boolean)
        """

        if error:
            log.error("error while deleting {}: {}".format(self.name(), result["message"]))
            self.server_error_signal.emit(self.id(), result["message"])
        log.info("{} has been deleted".format(self.name()))
        self.deleted_signal.emit()
        self._module.removeNode(self)

    def update(self, new_settings):
        """
        Updates the settings for this VPCS device.

        :param new_settings: settings dictionary
        """

        if "name" in new_settings and new_settings["name"] != self.name() and self.hasAllocatedName(new_settings["name"]):
            self.error_signal.emit(self.id(), 'Name "{}" is already used by another node'.format(new_settings["name"]))
            return

        params = {}
        for name, value in new_settings.items():
            if name in self._settings and self._settings[name] != value:
                params[name] = value

        log.debug("{} is updating settings: {}".format(self.name(), params))
        self._server.put("/vpcs/vms/{vm_id}".format(vm_id=self._vm_id), self._updateCallback, body=params)

    def _updateCallback(self, result, error=False):
        """
        Callback for update.

        :param result: server response (dict)
        :param error: indicates an error (boolean)
        """

        if error:
            log.error("error while deleting {}: {}".format(self.name(), result["message"]))
            self.server_error_signal.emit(self.id(), result["code"], result["message"])
            return

        updated = False
        for name, value in result.items():
            if name in self._settings and self._settings[name] != value:
                log.info("{}: updating {} from '{}' to '{}'".format(self.name(), name, self._settings[name], value))
                updated = True
                if name == "name":
                    # update the node name
                    self.updateAllocatedName(value)
                self._settings[name] = value

        if updated or self._loading:
            log.info("VPCS device {} has been updated".format(self.name()))
            self.updated_signal.emit()

    def start(self):
        """
        Starts this VPCS instance.
        """

        if self.status() == Node.started:
            log.debug("{} is already running".format(self.name()))
            return

        log.debug("{} is starting".format(self.name()))
        self._server.post("/vpcs/vms/{vm_id}/start".format(vm_id=self._vm_id), self._startCallback)

    def _startCallback(self, result, error=False):
        """
        Callback for start.

        :param result: server response (dict)
        :param error: indicates an error (boolean)
        """

        if error:
            log.error("error while starting {}: {}".format(self.name(), result["message"]))
            self.server_error_signal.emit(self.id(), result["message"])
        else:
            log.info("{} has started".format(self.name()))
            self.setStatus(Node.started)
            for port in self._ports:
                # set ports as started
                port.setStatus(Port.started)
            self.started_signal.emit()

    def stop(self):
        """
        Stops this VPCS instance.
        """

        if self.status() == Node.stopped:
            log.debug("{} is already stopped".format(self.name()))
            return

        log.debug("{} is stopping".format(self.name()))
        self._server.post("/vpcs/vms/{vm_id}/stop".format(vm_id=self._vm_id), self._stopCallback)

    def _stopCallback(self, result, error=False):
        """
        Callback for stop.

        :param result: server response (dict)
        :param error: indicates an error (boolean)
        """

        if error:
            log.error("error while stopping {}: {}".format(self.name(), result["message"]))
            self.server_error_signal.emit(self.id(), result["message"])
        else:
            log.info("{} has stopped".format(self.name()))
            self.setStatus(Node.stopped)
            for port in self._ports:
                # set ports as stopped
                port.setStatus(Port.stopped)
            self.stopped_signal.emit()

    def reload(self):
        """
        Reloads this VPCS instance.
        """

        log.debug("{} is being reloaded".format(self.name()))
        self._server.post("/vpcs/vms/{vm_id}/reload".format(vm_id=self._vm_id), self._reloadCallback)

    def _reloadCallback(self, result, error=False):
        """
        Callback for reload.

        :param result: server response (dict)
        :param error: indicates an error (boolean)
        """

        if error:
            log.error("error while suspending {}: {}".format(self.name(), result["message"]))
            self.server_error_signal.emit(self.id(), result["message"])
        else:
            log.info("{} has reloaded".format(self.name()))

    def allocateUDPPort(self, port_id):
        """
        Requests an UDP port allocation.

        :param port_id: port identifier
        """

        log.debug("{} is requesting an UDP port allocation".format(self.name()))
        self._server.post("/ports/udp", partial(self._allocateUDPPortCallback, port_id))

    def _allocateUDPPortCallback(self, port_id, result, error=False):
        """
        Callback for allocateUDPPort.

        :param result: server response (dict)
        :param error: indicates an error (boolean)
        """

        if error:
            log.error("error while allocating an UDP port for {}: {}".format(self.name(), result["message"]))
            self.server_error_signal.emit(self.id(), result["message"])
        else:
            lport = result["udp_port"]
            log.debug("{} has allocated UDP port {}".format(self.name(), port_id, lport))
            self.allocate_udp_nio_signal.emit(self.id(), port_id, lport)

    def addNIO(self, port, nio):
        """
        Adds a new NIO on the specified port for this VPCS instance.

        :param port: Port instance
        :param nio: NIO instance
        """

        params = self.getNIOInfo(nio)
        log.debug("{} is adding an {}: {}".format(self.name(), nio, params))
        self._server.post("/vpcs/vms/{vm_id}/ports/0/nio".format(vm_id=self._vm_id), partial(self._addNIOCallback, port.id()), params)

    def _addNIOCallback(self, port_id, result, error=False):
        """
        Callback for addNIO.

        :param result: server response (dict)
        :param error: indicates an error (boolean)
        """

        if error:
            log.error("error while adding an UDP NIO for {}: {}".format(self.name(), result["message"]))
            self.server_error_signal.emit(self.id(), result["message"])
            self.nio_cancel_signal.emit(self.id())
        else:
            self.nio_signal.emit(self.id(), port_id)

    def deleteNIO(self, port):
        """
        Deletes an NIO from the specified port on this VPCS instance

        :param port: Port instance
        """

        log.debug("{} is deleting an NIO".format(self.name()))
        self._server.delete("/vpcs/vms/{vm_id}/ports/0/nio".format(vm_id=self._vm_id), self._deleteNIOCallback)

    def _deleteNIOCallback(self, result, error=False):
        """
        Callback for deleteNIO.

        :param result: server response (dict)
        :param error: indicates an error (boolean)
        """

        if error:
            log.error("error while deleting NIO {}: {}".format(self.name(), result["message"]))
            self.server_error_signal.emit(self.id(), result["message"])
            return

        log.debug("{} has deleted a NIO: {}".format(self.name(), result))

    def info(self):
        """
        Returns information about this VPCS device.

        :returns: formated string
        """

        if self.status() == Node.started:
            state = "started"
        else:
            state = "stopped"

        info = """Device {name} is {state}
  Local node ID is {id}
  Server's VPCS device ID is {vm_id}
  console is on port {console}
""".format(name=self.name(),
           id=self.id(),
           vm_id=self._vm_id,
           state=state,
           console=self._settings["console"])

        port_info = ""
        for port in self._ports:
            if port.isFree():
                port_info += "     {port_name} is empty\n".format(port_name=port.name())
            else:
                port_info += "     {port_name} {port_description}\n".format(port_name=port.name(),
                                                                            port_description=port.description())

        return info + port_info

    def dump(self):
        """
        Returns a representation of this VPCS device.
        (to be saved in a topology file).

        :returns: representation of the node (dictionary)
        """

        vpcs_device = {"id": self.id(),
                       "vm_id": self._vm_id,
                       "type": self.__class__.__name__,
                       "description": str(self),
                       "properties": {},
                       "server_id": self._server.id()}

        # add the properties
        for name, value in self._settings.items():
            if name in self._defaults and self._defaults[name] != value:
                vpcs_device["properties"][name] = value

        # add the ports
        if self._ports:
            ports = vpcs_device["ports"] = []
            for port in self._ports:
                ports.append(port.dump())

        return vpcs_device

    def load(self, node_info):
        """
        Loads a VPCS device representation
        (from a topology file).

        :param node_info: representation of the node (dictionary)
        """

        self.node_info = node_info
        # for backward compatibility
        vm_id = node_info.get("vpcs_id")
        if not vm_id:
            vm_id = node_info["vm_id"]
        settings = node_info["properties"]
        name = settings.pop("name")
        self.updated_signal.connect(self._updatePortSettings)
        # block the created signal, it will be triggered when loading is completely done
        self._loading = True
        log.info("VPCS device {} is loading".format(name))
        self.setName(name)
        self.setup(name, vm_id, settings)

    def _updatePortSettings(self):
        """
        Updates port settings when loading a topology.
        """

        self.updated_signal.disconnect(self._updatePortSettings)
        # update the port with the correct names and IDs
        if "ports" in self.node_info:
            ports = self.node_info["ports"]
            for topology_port in ports:
                for port in self._ports:
                    if topology_port["port_number"] == port.portNumber():
                        port.setName(topology_port["name"])
                        port.setId(topology_port["id"])

        # now we can set the node has initialized and trigger the signal
        self.setInitialized(True)
        log.info("vpcs {} has been loaded".format(self.name()))
        self.created_signal.emit(self.id())
        self._module.addNode(self)
        self._inital_settings = None
        self._loading = False

    def exportConfig(self, config_export_path):
        """
        Exports the script file.

        :param config_export_path: export path for the script file
        """

        self._config_export_path = config_export_path
        self._server.get("/vpcs/vms/{vm_id}".format(vm_id=self._vm_id), self._exportConfigCallback)

    def _exportConfigCallback(self, result, error=False):
        """
        Callback for exportConfig.

        :param result: server response
        :param error: indicates an error (boolean)
        """

        if error:
            log.error("error while exporting {} configs: {}".format(self.name(), result["message"]))
            self.server_error_signal.emit(self.id(), result["code"], result["message"])
        else:

            if "startup_script" in result and self._config_export_path:
                try:
                    with open(self._config_export_path, "wb") as f:
                        log.info("saving {} script file to {}".format(self.name(), self._config_export_path))
                        f.write(result["startup_script"].encode("utf-8"))
                except OSError as e:
                    self.error_signal.emit(self.id(), "could not export the script file to {}: {}".format(self._config_export_path, e))

    def exportConfigToDirectory(self, directory):
        """
        Exports the script-file to a directory.

        :param directory: destination directory path
        """

        self._export_directory = directory
        self._server.get("/vpcs/vms/{vm_id}".format(vm_id=self._vm_id), self._exportConfigToDirectoryCallback)

    def _exportConfigToDirectoryCallback(self, result, error=False):
        """
        Callback for exportConfigToDirectory.

        :param result: server response
        :param error: indicates an error (boolean)
        """

        if error:
            log.error("error while exporting {} configs: {}".format(self.name(), result["message"]))
            self.server_error_signal.emit(self.id(), result["code"], result["message"])
        else:

            if "startup_script" in result:
                config_path = os.path.join(self._export_directory, normalize_filename(self.name())) + "_startup.vpc"
                config = result["startup_script"].encode("utf-8")
                try:
                    with open(config_path, "wb") as f:
                        log.info("saving {} script file to {}".format(self.name(), config_path))
                        f.write(config)
                except OSError as e:
                    self.error_signal.emit(self.id(), "could not export the script file to {}: {}".format(config_path, e))

            self._export_directory = None

    def importConfig(self, path):
        """
        Imports a script-file.

        :param path: path to the script file
        """

        with open(path) as f:
            new_settings = {"startup_script": f.read()}
        self.update(new_settings)

    def importConfigFromDirectory(self, directory):
        """
        Imports an initial-config from a directory.

        :param directory: source directory path
        """

        contents = os.listdir(directory)
        script_file = normalize_filename(self.name()) + "_startup.vpc"
        new_settings = {}
        if script_file in contents:
            new_settings["script_file"] = os.path.join(directory, script_file)
        else:
            self.warning_signal.emit(self.id(), "no script file could be found, expected file name: {}".format(script_file))
        if new_settings:
            self.update(new_settings)

    def vm_id(self):
        """
        Return the ID of this VPCS device

        :returns: identifier (string)
        """

        return self._vm_id

    def name(self):
        """
        Returns the name of this VPCS device.

        :returns: name (string)
        """

        return self._settings["name"]

    def settings(self):
        """
        Returns all this VPCS device settings.

        :returns: settings dictionary
        """

        return self._settings

    def ports(self):
        """
        Returns all the ports for this VPCS device.

        :returns: list of Port instances
        """

        return self._ports

    def console(self):
        """
        Returns the console port for this VPCS device.

        :returns: port (integer)
        """

        return self._settings["console"]

    def configPage(self):
        """
        Returns the configuration page widget to be used by the node configurator.

        :returns: QWidget object
        """

        from .pages.vpcs_device_configuration_page import VPCSDeviceConfigurationPage
        return VPCSDeviceConfigurationPage

    @staticmethod
    def defaultSymbol():
        """
        Returns the default symbol path for this node.

        :returns: symbol path (or resource).
        """

        return ":/symbols/computer.normal.svg"

    @staticmethod
    def hoverSymbol():
        """
        Returns the symbol to use when this node is hovered.

        :returns: symbol path (or resource).
        """

        return ":/symbols/computer.selected.svg"

    @staticmethod
    def symbolName():

        return "VPCS"

    @staticmethod
    def categories():
        """
        Returns the node categories the node is part of (used by the device panel).

        :returns: list of node category (integer)
        """

        return [Node.end_devices]

    def __str__(self):

        return "VPCS device"
