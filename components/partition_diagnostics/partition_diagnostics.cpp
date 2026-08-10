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

  const bool ota_partitions_match =
      this->flash_size_ >= 0x400000 && this->check_partition_(this->otadata_partition_, 0x9000, 0x2000) &&
      this->check_partition_(this->phy_partition_, 0xB000, 0x1000) &&
      this->check_partition_(this->app0_partition_, 0x10000, 0x1C0000) &&
      this->check_partition_(this->app1_partition_, 0x1D0000, 0x1C0000);
  this->ota_layout_compatible_ = ota_partitions_match && this->check_nvs_ota_compatible_(this->nvs_partition_);
  this->target_layout_matches_ =
      ota_partitions_match && this->check_partition_(this->nvs_partition_, 0x390000, 0x6D000);
}

bool PartitionDiagnosticsComponent::check_partition_(const esp_partition_t *partition, uint32_t address,
                                                      size_t size) const {
  return partition != nullptr && partition->address == address && partition->size == size;
}

bool PartitionDiagnosticsComponent::check_nvs_ota_compatible_(const esp_partition_t *partition) const {
  return partition != nullptr && partition->address == 0x390000 && partition->size >= 0x6D000 &&
         partition->size <= 0x70000 && partition->size % 0x1000 == 0;
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
  ESP_LOGCONFIG(TAG, "  Exact managed layout: %s", YESNO(this->target_layout_matches_));
  ESP_LOGCONFIG(TAG, "  OTA-compatible layout: %s", YESNO(this->ota_layout_compatible_));
  if (!this->ota_layout_compatible_) {
    ESP_LOGW(TAG, "App partition layout is not OTA-compatible; do not install public firmware yet");
  } else if (!this->target_layout_matches_) {
    ESP_LOGI(TAG, "Layout is OTA-compatible; only the non-app NVS allocation differs");
  }
}

}  // namespace esphome::partition_diagnostics
