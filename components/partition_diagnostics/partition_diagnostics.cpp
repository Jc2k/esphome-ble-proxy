#include "partition_diagnostics.h"

#include "esphome/core/log.h"

#include <esp_flash.h>
#include <esp_ota_ops.h>

#include <cinttypes>

namespace esphome::partition_diagnostics {

static const char *const TAG = "partition_diagnostics";

static const esp_partition_t *find_partition(esp_partition_type_t type, esp_partition_subtype_t subtype,
                                             const char *label) {
  return esp_partition_find_first(type, subtype, label);
}

void PartitionDiagnosticsComponent::setup() {
  esp_err_t flash_result = esp_flash_get_size(nullptr, &this->flash_size_);
  if (flash_result != ESP_OK) {
    ESP_LOGE(TAG, "Unable to determine flash size (err=0x%X)", flash_result);
    this->flash_size_ = 0;
  }

  this->running_partition_ = esp_ota_get_running_partition();
  this->otadata_partition_ =
      find_partition(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_OTA, "otadata");
  this->phy_partition_ = find_partition(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_PHY, "phy_init");
  this->app0_partition_ = find_partition(ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_APP_OTA_0, "app0");
  this->app1_partition_ = find_partition(ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_APP_OTA_1, "app1");
  this->nvs_partition_ = find_partition(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_NVS, "nvs");

  this->target_layout_matches_ = this->flash_size_ >= 0x400000 &&
                                 this->check_partition_(this->otadata_partition_, 0x9000, 0x2000) &&
                                 this->check_partition_(this->phy_partition_, 0xB000, 0x1000) &&
                                 this->check_partition_(this->app0_partition_, 0x10000, 0x1C0000) &&
                                 this->check_partition_(this->app1_partition_, 0x1D0000, 0x1C0000) &&
                                 this->check_partition_(this->nvs_partition_, 0x390000, 0x70000);
}

bool PartitionDiagnosticsComponent::check_partition_(const esp_partition_t *partition, uint32_t address,
                                                      size_t size) const {
  return partition != nullptr && partition->address == address && partition->size == size;
}

static void log_partition(const char *name, const esp_partition_t *partition) {
  if (partition == nullptr) {
    ESP_LOGCONFIG(TAG, "  %-8s: MISSING", name);
    return;
  }
  ESP_LOGCONFIG(TAG, "  %-8s: offset=0x%06" PRIX32 " size=0x%06" PRIX32 " (%" PRIu32 " bytes)", name,
                partition->address, partition->size, partition->size);
}

void PartitionDiagnosticsComponent::dump_config() {
  ESP_LOGCONFIG(TAG, "ESP32 partition diagnostics:");
  ESP_LOGCONFIG(TAG, "  Flash:    0x%06" PRIX32 " (%" PRIu32 " bytes)", this->flash_size_, this->flash_size_);
  log_partition("running", this->running_partition_);
  log_partition("otadata", this->otadata_partition_);
  log_partition("phy_init", this->phy_partition_);
  log_partition("app0", this->app0_partition_);
  log_partition("app1", this->app1_partition_);
  log_partition("nvs", this->nvs_partition_);
  ESP_LOGCONFIG(TAG, "  Target managed layout: %s", YESNO(this->target_layout_matches_));
  if (!this->target_layout_matches_) {
    ESP_LOGW(TAG, "Partition layout differs from the managed OTA layout; do not install public firmware yet");
  }
}

}  // namespace esphome::partition_diagnostics
