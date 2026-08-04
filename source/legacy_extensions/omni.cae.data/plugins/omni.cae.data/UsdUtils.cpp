// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: LicenseRef-NvidiaProprietary
//
// NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
// property and proprietary rights in and to this material, related
// documentation and any modifications thereto. Any use, reproduction,
// disclosure or distribution of this material and related documentation
// without an express license agreement from NVIDIA CORPORATION or
// its affiliates is strictly prohibited.

// .clang-format off
#include <omni/cae/data/IDataDelegateIncludes.h>
// .clang-format on

#include "UsdUtils.h"

#include <omniCae/dataSet.h>
#include <omniCae/fieldArray.h>
#include <pxr/usd/usd/attribute.h>
#include <pxr/usd/usd/relationship.h>

#include <algorithm>
#include <iterator>
#include <set>
#include <string>
#include <vector>

namespace omni
{
namespace cae
{
namespace data
{

namespace
{

bool hasPrefix(const std::string& value, const char* prefix)
{
    return value.rfind(prefix, 0) == 0;
}

bool isDataDependencyPrim(const pxr::UsdPrim& prim)
{
    if (!prim.IsValid())
    {
        return false;
    }

    // Legacy CAE schemas are concrete data prims.
    if (prim.IsA<pxr::OmniCaeDataSet>() || prim.IsA<pxr::OmniCaeFieldArray>())
    {
        return true;
    }

    // New file-format plugins author scientific data through OmniSci* typed prims
    // and API schemas. Avoid taking a hard build dependency on those schema
    // libraries here; string checks are enough for traversal and keep this utility
    // usable by both legacy and OmniSci-backed datasets.
    const std::string typeName = prim.GetTypeName().GetString();
    if (hasPrefix(typeName, "OmniSci") || hasPrefix(typeName, "OmniCgns"))
    {
        return true;
    }

    for (const pxr::TfToken& schemaName : prim.GetAppliedSchemas())
    {
        const std::string schema = schemaName.GetString();
        if (hasPrefix(schema, "OmniSci") || hasPrefix(schema, "OmniCgns"))
        {
            return true;
        }
    }

    return false;
}

std::vector<pxr::UsdAttribute> getTimeSampleCandidateAttributes(const pxr::UsdPrim& prim)
{
    std::vector<pxr::UsdAttribute> attrs = prim.GetAuthoredAttributes();
    std::set<pxr::SdfPath> seenAttrPaths;
    for (const pxr::UsdAttribute& attr : attrs)
    {
        seenAttrPaths.insert(attr.GetPath());
    }

    const std::string arrayPrefix = "OmniSciArrayAPI:";
    for (const pxr::TfToken& schemaName : prim.GetAppliedSchemas())
    {
        const std::string schema = schemaName.GetString();
        if (!hasPrefix(schema, arrayPrefix.c_str()))
        {
            continue;
        }

        const std::string instanceName = schema.substr(arrayPrefix.size());
        if (instanceName.empty())
        {
            continue;
        }

        const pxr::TfToken attrName(std::string("omni:sci:array:") + instanceName + ":value");
        pxr::UsdAttribute attr = prim.GetAttribute(attrName);
        if (attr.IsValid() && seenAttrPaths.insert(attr.GetPath()).second)
        {
            attrs.push_back(attr);
        }
    }

    return attrs;
}

} // namespace

bool UsdUtils::getBracketingTimeSamplesForPrim(
    const pxr::UsdPrim& prim, double time, double* lower, double* upper, bool* hasTimeSamples) const
{
    // Delegate to getBracketingTimeSamplesForDataSetPrim with traverseFieldRelationships=true
    // to avoid code duplication
    return getBracketingTimeSamplesForDataSetPrim(prim, time, true, lower, upper, hasTimeSamples);
}

void UsdUtils::populateTimeSamplesForDataSet(const pxr::UsdPrim& prim,
                                             double time,
                                             bool traverseFieldRelationships,
                                             std::set<double>& times,
                                             std::set<pxr::SdfPath>& processedPrims) const
{
    if (!prim.IsValid())
    {
        return;
    }

    const pxr::SdfPath& primPath = prim.GetPath();
    if (processedPrims.find(primPath) != processedPrims.end())
    {
        return; // Already processed, handle loops
    }

    processedPrims.insert(primPath);

    // Iterate over all visible authored attributes plus OmniSci lazy value
    // attributes. LazyArrayData intentionally hides heavy attrs from property
    // children, so GetAuthoredAttributes() alone cannot discover their time
    // samples.
    for (const auto& attr : getTimeSampleCandidateAttributes(prim))
    {
        double attrLower = 0.0;
        double attrUpper = 0.0;
        bool attrHasTimeSamples = false;
        if (attr.GetBracketingTimeSamples(time, &attrLower, &attrUpper, &attrHasTimeSamples) && attrHasTimeSamples)
        {
            times.insert(attrLower);
            times.insert(attrUpper);
        }
    }

    // Iterate over all authored relationships and recursively process targets
    pxr::UsdStageWeakPtr stage = prim.GetStage();
    if (!stage)
    {
        return;
    }

    for (const auto& rel : prim.GetAuthoredRelationships())
    {
        // Skip field relationships if traverseFieldRelationships is false
        if (!traverseFieldRelationships)
        {
            // Check if this is a field relationship (namespace starts with "field")
            // This matches Python's rel.GetNamespace().startswith("field") behavior
            pxr::TfToken namespaceToken = rel.GetNamespace();
            std::string namespaceStr = namespaceToken.GetString();
            bool isFieldRelationship = (namespaceStr.length() >= 5 && namespaceStr.compare(0, 5, "field") == 0);
            if (isFieldRelationship)
            {
                continue;
            }
        }

        pxr::SdfPathVector targets;
        if (rel.GetForwardedTargets(&targets))
        {
            for (const auto& targetPath : targets)
            {
                pxr::UsdPrim targetPrim = stage->GetPrimAtPath(targetPath);
                if (isDataDependencyPrim(targetPrim))
                {
                    populateTimeSamplesForDataSet(targetPrim, time, traverseFieldRelationships, times, processedPrims);
                }
            }
        }
    }
}

bool UsdUtils::getBracketingTimeSamplesForDataSetPrim(const pxr::UsdPrim& prim,
                                                      double time,
                                                      bool traverseFieldRelationships,
                                                      double* lower,
                                                      double* upper,
                                                      bool* hasTimeSamples) const
{
    const double earliestTime = pxr::UsdTimeCode::EarliestTime().GetValue();

    if (!prim.IsValid())
    {
        if (lower)
            *lower = earliestTime;
        if (upper)
            *upper = earliestTime;
        if (hasTimeSamples)
            *hasTimeSamples = false;
        return false;
    }

    std::set<double> times;
    std::set<pxr::SdfPath> processedPrims;

    populateTimeSamplesForDataSet(prim, time, traverseFieldRelationships, times, processedPrims);

    if (times.empty())
    {
        // No time samples exist, return EarliestTime
        if (lower)
            *lower = earliestTime;
        if (upper)
            *upper = earliestTime;
        if (hasTimeSamples)
            *hasTimeSamples = false;
        CARB_LOG_INFO("[cae.data.usd_utils][time] result prim=%s time=%g has=false lower=%g upper=%g visited=%zu",
                      prim.GetPath().GetText(), time, earliestTime, earliestTime, processedPrims.size());
        return true; // Operation succeeded, just no time samples
    }

    // Find the bracketing time samples using set's upper_bound (O(log n))
    // This matches Python's bisect_right behavior: returns insertion point after last element <= time
    auto it = times.upper_bound(time);

    if (it == times.end())
    {
        // Time is after the last time sample, return the last time sample
        if (lower)
            *lower = *times.rbegin();
        if (upper)
            *upper = *times.rbegin();
        if (hasTimeSamples)
            *hasTimeSamples = true;
        CARB_LOG_INFO(
            "[cae.data.usd_utils][time] result prim=%s time=%g has=true lower=%g upper=%g visited=%zu samples=%zu",
            prim.GetPath().GetText(), time, *times.rbegin(), *times.rbegin(), processedPrims.size(), times.size());
        return true;
    }

    if (it == times.begin())
    {
        // Time is before the first time sample, return the first time sample
        if (lower)
            *lower = *times.begin();
        if (upper)
            *upper = *times.begin();
        if (hasTimeSamples)
            *hasTimeSamples = true;
        CARB_LOG_INFO(
            "[cae.data.usd_utils][time] result prim=%s time=%g has=true lower=%g upper=%g visited=%zu samples=%zu",
            prim.GetPath().GetText(), time, *times.begin(), *times.begin(), processedPrims.size(), times.size());
        return true;
    }

    // Get the previous element
    auto prevIt = std::prev(it);

    // Check if the previous element equals time (exact match)
    if (*prevIt == time)
    {
        // Exact match, return the same time sample
        if (lower)
            *lower = *prevIt;
        if (upper)
            *upper = *prevIt;
        if (hasTimeSamples)
            *hasTimeSamples = true;
        CARB_LOG_INFO(
            "[cae.data.usd_utils][time] result prim=%s time=%g has=true lower=%g upper=%g visited=%zu samples=%zu",
            prim.GetPath().GetText(), time, *prevIt, *prevIt, processedPrims.size(), times.size());
        return true;
    }

    // Time is between two time samples, return the bracketing samples
    if (lower)
        *lower = *prevIt;
    if (upper)
        *upper = *it;
    if (hasTimeSamples)
        *hasTimeSamples = true;
    CARB_LOG_INFO("[cae.data.usd_utils][time] result prim=%s time=%g has=true lower=%g upper=%g visited=%zu samples=%zu",
                  prim.GetPath().GetText(), time, *prevIt, *it, processedPrims.size(), times.size());
    return true;
}

void UsdUtils::collectRelatedDataPrims(const pxr::UsdPrim& prim,
                                       bool transitive,
                                       std::set<pxr::SdfPath>& processedPrims,
                                       std::vector<pxr::UsdPrim>& result,
                                       const std::vector<std::string>& relNames) const
{
    if (!prim.IsValid())
    {
        return;
    }

    const pxr::SdfPath& primPath = prim.GetPath();
    if (processedPrims.find(primPath) != processedPrims.end())
    {
        return; // Already processed, handle loops
    }

    processedPrims.insert(primPath);

    // Traverse relationships, optionally filtered to a specific name set (first-hop only).
    for (const auto& rel : prim.GetAuthoredRelationships())
    {
        // If relNames is non-empty, skip relationships not in the set.
        if (!relNames.empty())
        {
            const std::string relName = rel.GetName().GetString();
            if (std::find(relNames.begin(), relNames.end(), relName) == relNames.end())
            {
                continue;
            }
        }

        pxr::SdfPathVector targets;
        if (rel.GetForwardedTargets(&targets))
        {
            for (const auto& targetPath : targets)
            {
                const pxr::UsdStageRefPtr& stage = prim.GetStage();
                if (!stage)
                {
                    continue;
                }

                pxr::UsdPrim targetPrim = stage->GetPrimAtPath(targetPath);
                if (isDataDependencyPrim(targetPrim))
                {
                    // Add this prim to the result
                    result.push_back(targetPrim);

                    // If transitive, recursively collect from this target using no rel filter —
                    // once inside the subgraph we follow all relationships freely.
                    if (transitive)
                    {
                        collectRelatedDataPrims(targetPrim, transitive, processedPrims, result, {});
                    }
                }
            }
        }
    }
}

std::vector<pxr::UsdPrim> UsdUtils::getRelatedDataPrims(const pxr::UsdPrim& prim,
                                                        bool transitive,
                                                        bool includeSelf,
                                                        const std::vector<std::string>& relNames) const
{
    std::vector<pxr::UsdPrim> result;
    std::set<pxr::SdfPath> processedPrims;

    // If includeSelf is true, add the prim regardless of its type
    if (includeSelf && prim.IsValid())
    {
        result.push_back(prim);
        // Don't add to processedPrims here - we still want to traverse its relationships
    }

    // Collect related prims (will add prim to processedPrims to avoid cycles)
    collectRelatedDataPrims(prim, transitive, processedPrims, result, relNames);

    return result;
}

} // namespace data
} // namespace cae
} // namespace omni
