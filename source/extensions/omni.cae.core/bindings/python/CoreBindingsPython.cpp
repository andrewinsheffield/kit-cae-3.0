// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: LicenseRef-NvidiaProprietary
//
// NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
// property and proprietary rights in and to this material, related
// documentation and any modifications thereto. Any use, reproduction,
// disclosure or distribution of this material and related documentation
// without an express license agreement from NVIDIA CORPORATION or
// its affiliates is strictly prohibited.

#define PYBIND11_DETAILED_ERROR_MESSAGES

#include <carb/BindingsPythonUtils.h>

#include <omniCae/dataSet.h>
#include <omniCae/fieldArray.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/usd/attribute.h>
#include <pxr/usd/usd/prim.h>
#include <pxr/usd/usd/relationship.h>
#include <pxr/usd/usd/stage.h>
#include <pxr/usd/usd/timeCode.h>
#include <pxr/usd/usdUtils/stageCache.h>
#include <pybind11/pybind11.h>

#include <algorithm>
#include <iterator>
#include <set>
#include <string>
#include <vector>

namespace py = pybind11;

CARB_BINDINGS("omni.cae.core.python")

namespace
{

bool hasPrefix(const std::string& value, const char* prefix)
{
    return value.rfind(prefix, 0) == 0;
}

pxr::UsdStageRefPtr getStage(long int stageId)
{
    return pxr::UsdUtilsStageCache::Get().Find(pxr::UsdStageCache::Id::FromLongInt(stageId));
}

bool isDataDependencyPrim(const pxr::UsdPrim& prim)
{
    if (!prim.IsValid())
    {
        return false;
    }

    if (prim.IsA<pxr::OmniCaeDataSet>() || prim.IsA<pxr::OmniCaeFieldArray>())
    {
        return true;
    }

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

void populateTimeSamplesForDataSet(const pxr::UsdPrim& prim,
                                   double time,
                                   bool traverseFieldRelationships,
                                   std::set<double>& times,
                                   std::set<pxr::SdfPath>& processedPrims)
{
    if (!prim.IsValid())
    {
        return;
    }

    const pxr::SdfPath& primPath = prim.GetPath();
    if (!processedPrims.insert(primPath).second)
    {
        return;
    }

    for (const pxr::UsdAttribute& attr : getTimeSampleCandidateAttributes(prim))
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

    pxr::UsdStageWeakPtr stage = prim.GetStage();
    if (!stage)
    {
        return;
    }

    for (const pxr::UsdRelationship& rel : prim.GetAuthoredRelationships())
    {
        if (!traverseFieldRelationships)
        {
            const std::string namespaceStr = rel.GetNamespace().GetString();
            if (hasPrefix(namespaceStr, "field"))
            {
                continue;
            }
        }

        pxr::SdfPathVector targets;
        if (!rel.GetForwardedTargets(&targets))
        {
            continue;
        }

        for (const pxr::SdfPath& targetPath : targets)
        {
            pxr::UsdPrim targetPrim = stage->GetPrimAtPath(targetPath);
            if (isDataDependencyPrim(targetPrim))
            {
                populateTimeSamplesForDataSet(targetPrim, time, traverseFieldRelationships, times, processedPrims);
            }
        }
    }
}

py::tuple makeNoTimeSamplesTuple()
{
    const double earliestTime = pxr::UsdTimeCode::EarliestTime().GetValue();
    return py::make_tuple(earliestTime, earliestTime, false);
}

py::tuple getBracketingTimeSamplesForDataSetPrim(long int stageId,
                                                 const std::string& primPath,
                                                 double time,
                                                 bool traverseFieldRelationships)
{
    pxr::UsdStageRefPtr stage = getStage(stageId);
    if (!stage)
    {
        return makeNoTimeSamplesTuple();
    }

    pxr::UsdPrim prim = stage->GetPrimAtPath(pxr::SdfPath(primPath));
    if (!prim.IsValid())
    {
        return makeNoTimeSamplesTuple();
    }

    std::set<double> times;
    std::set<pxr::SdfPath> processedPrims;

    {
        py::gil_scoped_release release;
        populateTimeSamplesForDataSet(prim, time, traverseFieldRelationships, times, processedPrims);
    }

    if (times.empty())
    {
        return makeNoTimeSamplesTuple();
    }

    auto it = times.upper_bound(time);
    if (it == times.end())
    {
        const double last = *times.rbegin();
        return py::make_tuple(last, last, true);
    }
    if (it == times.begin())
    {
        const double first = *times.begin();
        return py::make_tuple(first, first, true);
    }

    const auto prevIt = std::prev(it);
    if (*prevIt == time)
    {
        return py::make_tuple(*prevIt, *prevIt, true);
    }

    return py::make_tuple(*prevIt, *it, true);
}

py::tuple getBracketingTimeSamplesForPrim(long int stageId, const std::string& primPath, double time)
{
    return getBracketingTimeSamplesForDataSetPrim(stageId, primPath, time, true);
}

} // namespace

PYBIND11_MODULE(_omni_cae_core, m)
{
    m.doc() = "Private native helpers for omni.cae.core.";

    m.def("get_bracketing_time_samples_for_prim", &getBracketingTimeSamplesForPrim, py::arg("stage_id"),
          py::arg("prim_path"), py::arg("time"),
          R"(
        Get bracketing time samples for a prim using native USD traversal.
        )");

    m.def("get_bracketing_time_samples_for_data_set_prim", &getBracketingTimeSamplesForDataSetPrim, py::arg("stage_id"),
          py::arg("prim_path"), py::arg("time"), py::arg("traverse_field_relationships") = true,
          R"(
        Get bracketing time samples for a dataset prim using native USD traversal.
        )");
}
