import base64

from esphome import codegen as cg
from esphome.components import api
import esphome.config_validation as cv
from esphome.const import CONF_ID


CONF_API_ENCRYPTION_KEY = "api_encryption_key"

managed_config_ns = cg.esphome_ns.namespace("managed_config")
ManagedConfigComponent = managed_config_ns.class_("ManagedConfigComponent", cg.Component)

DEPENDENCIES = ["api"]

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(ManagedConfigComponent),
        cv.Optional(CONF_API_ENCRYPTION_KEY): cv.sensitive(api.validate_encryption_key),
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    if key := config.get(CONF_API_ENCRYPTION_KEY):
        cg.add(var.set_api_encryption_key(list(base64.b64decode(key))))
